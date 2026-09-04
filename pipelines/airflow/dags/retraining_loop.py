"""Closed-loop retraining DAG. Every 6h: drift check -> retrain -> evaluate -> promote."""
import json
import os
from datetime import datetime, timedelta, timezone

import boto3
from airflow import DAG
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import BranchPythonOperator, PythonOperator
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator

BUCKET = os.getenv("PREDICTION_BUCKET", "anomaly-mlops-artifacts-dev")
IMAGE = os.getenv("ANOMALY_IMAGE", "170420138680.dkr.ecr.ap-south-1.amazonaws.com/anomaly-mlops:553ec6c")
# Overridable so a demo run does not sit through a full-length training job.
RETRAIN_EPOCHS = os.getenv("RETRAIN_EPOCHS", "20")
MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow.mlops.svc.cluster.local:5000")
MARKER_KEY = "drift/drift_detected.json"

default_args = {"owner": "mlops", "retries": 2, "retry_delay": timedelta(minutes=5)}

COMMON_ENV = {
    "PREDICTION_BUCKET": BUCKET,
    "MLFLOW_TRACKING_URI": MLFLOW_URI,
}


def check_drift(**_):
    """Branch to retraining only if a fresh drift marker exists."""
    s3 = boto3.client("s3")
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=MARKER_KEY)
    except s3.exceptions.NoSuchKey:
        return "skip"
    marker = json.loads(obj["Body"].read())
    detected_at = datetime.fromisoformat(marker["detected_at"])
    if detected_at.tzinfo is None:
        detected_at = detected_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - detected_at
    return "retrain" if age < timedelta(hours=6) else "skip"


def clear_marker(**_):
    """Consume the marker so a single drift event triggers a single retrain."""
    boto3.client("s3").delete_object(Bucket=BUCKET, Key=MARKER_KEY)


with DAG(
    "anomaly_retraining_loop",
    default_args=default_args,
    schedule="0 */6 * * *",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    tags=["mlops", "anomaly"],
) as dag:

    # service_account_name is not optional here. Task pods land in `mlops` and
    # would otherwise get that namespace's `default` service account, which has no
    # IRSA annotation — S3 access would silently fall back to the node role's
    # broader grant, or fail outright once that grant is removed.
    drift_job = KubernetesPodOperator(
        task_id="drift_check", name="drift-check", namespace="mlops",
        service_account_name="anomaly-sa",
        image=IMAGE, cmds=["python", "-m", "src.drift.detect"],
        env_vars={
            **COMMON_ENV,
            "DRIFT_THRESHOLD": "0.5",
            # Look back one scheduling interval, not a flat 24h: a check that runs
            # every 6h and reads a day of history averages a fresh shift away
            # against hours of in-distribution traffic that preceded it.
            "DRIFT_WINDOW_HOURS": "6",
            # Each prediction is one S3 object and the job issues one GET per
            # record, so an unbounded window is also an unbounded bill. 2,500 rows
            # is far more than the drift test needs to be significant.
            "DRIFT_MAX_OBJECTS": "2500",
        },
        get_logs=True)

    branch = BranchPythonOperator(task_id="branch", python_callable=check_drift)

    # train.py writes the MLflow run id to /airflow/xcom/return.json so the
    # promotion gate below knows which candidate to evaluate.
    retrain = KubernetesPodOperator(
        task_id="retrain", name="retrain", namespace="mlops", image=IMAGE,
        service_account_name="anomaly-sa",
        cmds=["python", "-m", "src.training.train",
              "--model", "lstm_ae", "--experiment", "auto-retrain",
              "--epochs", RETRAIN_EPOCHS],
        env_vars=COMMON_ENV,
        do_xcom_push=True, get_logs=True)

    promote = KubernetesPodOperator(
        task_id="promote", name="promote", namespace="mlops", image=IMAGE,
        service_account_name="anomaly-sa",
        # A rejected candidate is a correct outcome, not a task failure — the gate
        # did its job and the champion stays. Only an error inside promote() should
        # turn the task red, so the decision is logged and the exit code stays 0.
        cmds=["python", "-c",
              "import os; from src.training.evaluate import promote; "
              "print('PROMOTED' if promote(os.environ['RUN_ID']) else "
              "'REJECTED — champion retained')"],
        env_vars={**COMMON_ENV, "RUN_ID": "{{ ti.xcom_pull(task_ids='retrain') }}"},
        get_logs=True)

    clear = PythonOperator(task_id="clear_marker", python_callable=clear_marker)

    skip = EmptyOperator(task_id="skip")

    drift_job >> branch >> [retrain, skip]
    retrain >> promote >> clear
