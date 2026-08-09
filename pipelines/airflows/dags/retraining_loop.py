"""Closed-loop retraining DAG. Every 6h: drift check -> retrain -> evaluate -> promote."""
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import BranchPythonOperator
from airflow.operators.empty import EmptyOperator
from airflow.providers.cncf.kubernetes.operators.pod import KubernetesPodOperator

import boto3
import json
import os

BUCKET = os.getenv("PREDICTION_BUCKET", "anomaly-mlops-artifacts-dev")
IMAGE = os.getenv("ANOMALY_IMAGE", "PLACEHOLDER_ECR_URI/anomaly-mlops:latest")

default_args = {"owner": "mlops", "retries": 2, "retry_delay": timedelta(minutes=5)}


def check_drift(**_):
    s3 = boto3.client("s3")
    try:
        obj = s3.get_object(Bucket=BUCKET, Key="drift/drift_detected.json")
        marker = json.loads(obj["Body"].read())
        ts = datetime.fromisoformat(marker["detected_at"])
        if datetime.utcnow().replace(tzinfo=ts.tzinfo) - ts < timedelta(hours=6):
            return "retrain"
    except s3.exceptions.NoSuchKey:
        pass
    return "skip"


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
        env_vars={"PREDICTION_BUCKET": BUCKET, "DRIFT_THRESHOLD": "0.5"},
        get_logs=True)

    branch = BranchPythonOperator(task_id="branch", python_callable=check_drift)

    retrain = KubernetesPodOperator(
        task_id="retrain", name="retrain", namespace="mlops", image=IMAGE,
        cmds=["python", "-m", "src.training.train",
              "--model", "lstm_ae", "--experiment", "auto-retrain", "--epochs", "20"],
        do_xcom_push=True, get_logs=True)

    promote = KubernetesPodOperator(
        task_id="promote", name="promote", namespace="mlops", image=IMAGE,
        cmds=["python", "-c",
              "from src.training.evaluate import promote; import os; "
              "promote(os.environ['RUN_ID'])"],
        env_vars={"RUN_ID": "{{ ti.xcom_pull(task_ids='retrain') }}"}, get_logs=True)

    skip = EmptyOperator(task_id="skip")

    drift_job >> branch >> [retrain, skip]
    retrain >> promote