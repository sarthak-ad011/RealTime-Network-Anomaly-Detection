"""Drift detection job. Compares recent live predictions to the training reference.

Writes a marker to S3 when the share of drifted feature columns exceeds the
threshold; the Airflow DAG branches on that marker to trigger retraining.
Runs as a KubernetesPodOperator task (see pipelines/airflow/dags/retraining_loop.py).
"""
from __future__ import annotations

import io
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import boto3
import pandas as pd
from evidently import DataDefinition, Dataset, Report
from evidently.presets import DataDriftPreset
from loguru import logger

from src.data.loader import FEATURE_COLS

BUCKET = os.getenv("PREDICTION_BUCKET", "anomaly-mlops-artifacts-dev")
THRESHOLD = float(os.getenv("DRIFT_THRESHOLD", "0.5"))
REFERENCE_KEY = os.getenv("REFERENCE_KEY", "reference/training_reference.parquet")
MARKER_KEY = os.getenv("DRIFT_MARKER_KEY", "drift/drift_detected.json")
MAX_OBJECTS = int(os.getenv("DRIFT_MAX_OBJECTS", "20000"))
MIN_ROWS = int(os.getenv("DRIFT_MIN_ROWS", "100"))
# How far back to look. The default matches the 6-hourly DAG with room to spare;
# a shorter window isolates a recent traffic change from the day's backlog, which
# otherwise averages a genuine shift away into hours of in-distribution history.
WINDOW_HOURS = float(os.getenv("DRIFT_WINDOW_HOURS", "24"))

s3 = boto3.client("s3")


def _read_record(key):
    try:
        body = s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
        rec = json.loads(body)
        return dict(zip(rec["feature_names"], rec["features"], strict=True))
    except Exception as exc:  # a single unreadable record must not kill the job
        logger.warning(f"skipping {key}: {exc}")
        return None


def load_recent(hours: float = WINDOW_HOURS) -> pd.DataFrame:
    """Fetch prediction records written in the last `hours` from S3."""
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    candidates = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix="predictions/"):
        for obj in page.get("Contents", []):
            if obj["LastModified"] >= cutoff:
                candidates.append((obj["LastModified"], obj["Key"]))
    # Keep the NEWEST objects when capping. S3 lists keys lexicographically and the
    # keys are UUIDs, so truncating the listing would sample arbitrarily across the
    # window and could omit the very traffic a drift check is meant to notice.
    candidates.sort(key=lambda kv: kv[0], reverse=True)
    if len(candidates) > MAX_OBJECTS:
        logger.warning(f"capping at the {MAX_OBJECTS} most recent of {len(candidates)} objects")
        candidates = candidates[:MAX_OBJECTS]
    keys = [k for _, k in candidates]
    # one GET per record: fan out so a few thousand objects don't take minutes
    with ThreadPoolExecutor(max_workers=32) as pool:
        rows = [r for r in pool.map(_read_record, keys) if r is not None]
    df = pd.DataFrame(rows)
    logger.info(f"loaded {len(df)} recent predictions from {len(keys)} objects")
    return df


def load_reference() -> pd.DataFrame:
    body = s3.get_object(Bucket=BUCKET, Key=REFERENCE_KEY)["Body"].read()
    return pd.read_parquet(io.BytesIO(body))


def compute_drift(reference: pd.DataFrame, current: pd.DataFrame) -> dict:
    """Run the Evidently drift preset and return a flat summary."""
    common = [c for c in FEATURE_COLS if c in reference.columns and c in current.columns]
    if not common:
        raise RuntimeError("no overlapping feature columns between reference and current")
    definition = DataDefinition(numerical_columns=common)
    ref_ds = Dataset.from_pandas(reference[common], data_definition=definition)
    cur_ds = Dataset.from_pandas(current[common], data_definition=definition)
    snapshot = Report([DataDriftPreset()]).run(cur_ds, ref_ds)

    counts = next(
        m for m in snapshot.dict()["metrics"]
        if m["config"]["type"].endswith("DriftedColumnsCount")
    )["value"]
    return {
        "number_of_columns": len(common),
        "number_of_drifted_columns": int(counts["count"]),
        "share_of_drifted_columns": float(counts["share"]),
        "dataset_drift": bool(float(counts["share"]) > THRESHOLD),
    }


def main():
    current = load_recent()
    if len(current) < MIN_ROWS:
        logger.info(f"only {len(current)} recent predictions (< {MIN_ROWS}); skipping")
        return
    summary = compute_drift(load_reference(), current)
    logger.info(f"drift summary: {summary}")
    if summary["dataset_drift"]:
        marker = {"detected_at": datetime.now(UTC).isoformat(), **summary}
        s3.put_object(Bucket=BUCKET, Key=MARKER_KEY, Body=json.dumps(marker).encode())
        logger.warning(
            f"drift marker written: {summary['number_of_drifted_columns']}"
            f"/{summary['number_of_columns']} columns drifted"
        )
    else:
        logger.info("no significant drift")


if __name__ == "__main__":
    main()
