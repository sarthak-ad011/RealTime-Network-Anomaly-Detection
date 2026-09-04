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
IMAGE = os.getenv("ANOMALY_IMAGE", "PLACEHOLDER_ECR_URI/anomaly-mlops:latest")
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

    drift_job = KubernetesPodOperator(
        task_id="drift_check", name="drift-check", namespace="mlops",
        image=IMAGE, cmds=["python", "-m", "src.drift.detect"],
        env_vars={**COMMON_ENV, "DRIFT_THRESHOLD": "0.5"},
        get_logs=True)

    branch = BranchPythonOperator(task_id="branch", python_callable=check_drift)

    # train.py writes the MLflow run id to /airflow/xcom/return.json so the
    # promotion gate below knows which candidate to evaluate.
    retrain = KubernetesPodOperator(
        task_id="retrain", name="retrain", namespace="mlops", image=IMAGE,
        cmds=["python", "-m", "src.training.train",
              "--model", "lstm_ae", "--experiment", "auto-retrain", "--epochs", "20"],
        env_vars=COMMON_ENV,
        do_xcom_push=True, get_logs=True)

    promote = KubernetesPodOperator(
        task_id="promote", name="promote", namespace="mlops", image=IMAGE,
        cmds=["python", "-c",
              "import os; from src.training.evaluate import promote; "
              "raise SystemExit(0 if promote(os.environ['RUN_ID']) else 0)"],
        env_vars={**COMMON_ENV, "RUN_ID": "{{ ti.xcom_pull(task_ids='retrain') }}"},
        get_logs=True)

    clear = PythonOperator(task_id="clear_marker", python_callable=clear_marker)

    skip = EmptyOperator(task_id="skip")

    drift_job >> branch >> [retrain, skip]
    retrain >> promote >> clear
