"""Publish a locally-trained model into a target MLflow registry.

Training runs on a workstation (or a training pod) against a local tracking store,
but the serving pods read from the cluster registry backed by RDS + S3. This copies
a finished run's params, metrics and model artifacts across and assigns a stage, so
the champion (Production) and shadow (Staging) slots can be filled without retraining
inside the cluster.

Usage:
    python scripts/seed_registry.py \
        --source-uri http://127.0.0.1:5000 \
        --target-uri http://127.0.0.1:5001 \
        --run-id <local run id> --stage Production
"""
from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

import mlflow
from mlflow.tracking import MlflowClient

MODEL_NAME = "network-anomaly-detector"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-uri", required=True)
    ap.add_argument("--target-uri", required=True)
    ap.add_argument("--run-id", required=True, help="run id in the SOURCE registry")
    ap.add_argument("--stage", default="Production", choices=["Production", "Staging"])
    ap.add_argument("--experiment", default="seeded")
    args = ap.parse_args()

    src = MlflowClient(tracking_uri=args.source_uri)
    run = src.get_run(args.run_id)
    print(f"source run {args.run_id}: {len(run.data.metrics)} metrics, {len(run.data.params)} params")

    tmp = Path(tempfile.mkdtemp())
    try:
        local_dir = Path(src.download_artifacts(args.run_id, "model", str(tmp)))
        files = sorted(p.name for p in local_dir.iterdir())
        print(f"downloaded model artifacts: {files}")
        if not any(f.endswith(".pt") for f in files):
            raise SystemExit("no .pt checkpoint under the run's model/ path")
        if not any(f.endswith("_scaler.pkl") for f in files):
            raise SystemExit("no *_scaler.pkl under the run's model/ path")

        mlflow.set_tracking_uri(args.target_uri)
        mlflow.set_experiment(args.experiment)
        with mlflow.start_run() as new_run:
            mlflow.log_params(run.data.params)
            mlflow.log_metrics(run.data.metrics)
            mlflow.set_tag("seeded_from_run", args.run_id)
            mlflow.log_artifacts(str(local_dir), "model")
            target_run_id = new_run.info.run_id
        print(f"target run: {target_run_id}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    tgt = MlflowClient(tracking_uri=args.target_uri)
    try:
        tgt.create_registered_model(MODEL_NAME)
    except Exception:
        pass  # already exists
    version = tgt.create_model_version(
        name=MODEL_NAME,
        source=f"runs:/{target_run_id}/model",
        run_id=target_run_id,
    )
    tgt.transition_model_version_stage(MODEL_NAME, version.version, args.stage)
    print(f"registered {MODEL_NAME} v{version.version} -> {args.stage}")


if __name__ == "__main__":
    main()
