#!/usr/bin/env bash
# Phase 11 — install the Airflow orchestration layer.
#
# Airflow closes the loop the rest of the platform opens: drift detection writes a
# marker to S3, and this scheduler is what notices it and drives retrain -> evaluate
# -> promote without a human. Everything else (Argo CD, Argo Rollouts, Prometheus)
# is installed by scripts/deploy_platform.sh; this is kept separate because it is
# the only component that needs a database provisioned first.
#
# Prerequisites: kubeconfig pointing at the cluster, and `source ~/.anomaly-mlops-dev.env`
# for TF_VAR_db_password (the RDS master password, reused for the airflow database).
set -euo pipefail

NS="${AIRFLOW_NS:-airflow}"
RELEASE="${AIRFLOW_RELEASE:-airflow}"
CHART_VERSION="${AIRFLOW_CHART_VERSION:-1.16.0}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

: "${TF_VAR_db_password:?set TF_VAR_db_password (source ~/.anomaly-mlops-dev.env)}"

# Reuse the RDS endpoint MLflow already points at rather than hardcoding it, so this
# keeps working across a terraform destroy/apply cycle that moves the instance.
RDS_HOST="$(kubectl -n mlops get secret mlflow-db -o jsonpath='{.data.backend_uri}' \
  | base64 -d | sed -E 's#.*@([^:/]+).*#\1#')"
echo "==> RDS host: ${RDS_HOST}"

echo "==> namespace ${NS}"
kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -

# The airflow database itself is created by scripts/create_airflow_db.py, run through
# the MLflow pod (it is the only thing in the cluster with a Postgres driver and a
# route to RDS, which lives in a private subnet).
echo "==> ensuring 'airflow' database exists on RDS"
kubectl -n mlops exec -i deploy/mlflow -- python - < "${ROOT}/scripts/create_airflow_db.py"

echo "==> metadata + webserver secrets"
kubectl -n "$NS" create secret generic airflow-metadata \
  --from-literal=connection="postgresql://mlflow:${TF_VAR_db_password}@${RDS_HOST}:5432/airflow" \
  --dry-run=client -o yaml | kubectl apply -f -

# Stable across upgrades: a regenerated key invalidates every active session and, for
# the Fernet key, every encrypted Connection already in the database.
if ! kubectl -n "$NS" get secret airflow-webserver-secret >/dev/null 2>&1; then
  kubectl -n "$NS" create secret generic airflow-webserver-secret \
    --from-literal=webserver-secret-key="$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
fi

echo "==> cross-namespace pod-launcher RBAC"
kubectl apply -f "${ROOT}/k8s/airflow/pod-launcher-rbac.yaml"

echo "==> helm upgrade --install ${RELEASE} (chart ${CHART_VERSION})"
helm repo add apache-airflow https://airflow.apache.org >/dev/null 2>&1 || true
helm repo update >/dev/null
helm upgrade --install "$RELEASE" apache-airflow/airflow \
  --namespace "$NS" \
  --version "$CHART_VERSION" \
  --values "${ROOT}/k8s/airflow/values.yaml" \
  --timeout 15m \
  --wait

echo
echo "==> done. UI:"
echo "   kubectl -n ${NS} port-forward svc/${RELEASE}-webserver 8080:8080"
echo "   http://localhost:8080  (admin / admin)"
echo "   then unpause the 'anomaly_retraining_loop' DAG"
