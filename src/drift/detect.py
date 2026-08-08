"""Drift detection job. Compares last 24h of predictions to the training reference.
Writes a marker to S3 if drift exceeds threshold. Runs as an Airflow task."""
from __future__ import annotations

import os
import json
from datetime import datetime, timedelta, timezone

import boto3
import pandas as pd
from evidently.report import Report
from evidently.metric_preset import DataDriftPreset
from loguru import logger

from src.data.loader import FEATURE_COLS

BUCKET = os.getenv("PREDICTION_BUCKET", "anomaly-mlops-artifacts-dev")
THRESHOLD = float(os.getenv("DRIFT_THRESHOLD", "0.5"))
s3 = boto3.client("s3")


def load_recent(hours=24):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    rows = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix="predictions/"):
        for obj in page.get("Contents", []):
            if obj["LastModified"] < cutoff:
                continue
            body = s3.get_object(Bucket=BUCKET, Key=obj["Key"])["Body"].read()
            rec = json.loads(body)
            rows.append(dict(zip(rec["feature_names"], rec["features"])))
    df = pd.DataFrame(rows)
    logger.info(f"loaded {len(df)} recent predictions")
    return df


def main():
    current = load_recent()
    if len(current) < 100:
        logger.info("not enough recent predictions; skipping")
        return
    ref = pd.read_parquet(
        s3.get_object(Bucket=BUCKET, Key="reference/training_reference.parquet")["Body"])
    common = [c for c in FEATURE_COLS if c in ref.columns and c in current.columns]
    report = Report(metrics=[DataDriftPreset()])
    report.run(reference_data=ref[common], current_data=current[common])
    summary = report.as_dict()["metrics"][0]["result"]
    logger.info(f"drift summary: {summary}")
    if summary["share_of_drifted_columns"] > THRESHOLD:
        s3.put_object(Bucket=BUCKET, Key="drift/drift_detected.json",
                      Body=json.dumps({"detected_at": datetime.now(timezone.utc).isoformat(),
                                       **{k: summary[k] for k in
                                          ["number_of_columns", "number_of_drifted_columns",
                                           "share_of_drifted_columns", "dataset_drift"]}}).encode())
        logger.warning("drift marker written")
    else:
        logger.info("no significant drift")


if __name__ == "__main__":
    main()