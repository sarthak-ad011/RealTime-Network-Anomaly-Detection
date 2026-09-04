#!/usr/bin/env bash
# Bootstrap the cluster platform after `terraform apply`.
#
# Installs, in dependency order: Argo Rollouts (CRDs the app manifests need),
# kube-prometheus-stack (the canary AnalysisTemplate queries it), and Argo CD.
# Idempotent — safe to re-run.
#
# Requires: TF_VAR_db_password exported (same value used for `terraform apply`).
set -euo pipefail

REGION="${AWS_REGION:-ap-south-1}"
TF_DIR="${TF_DIR:-terraform/environments/dev}"
CLUSTER="${CLUSTER_NAME:-anomaly-dev}"

: "${TF_VAR_db_password:?export TF_VAR_db_password (same value used for terraform apply)}"

echo "==> kubeconfig for $CLUSTER"
# Some resolvers fail specifically on eks.<region>.amazonaws.com while every other
# AWS endpoint resolves. AWS publishes a dual-stack endpoint for the same API, so
# fall back to it rather than failing the whole bootstrap.
if ! aws eks describe-cluster --name "$CLUSTER" --region "$REGION" >/dev/null 2>&1; then
  echo "    standard EKS endpoint unreachable; retrying via dual-stack"
  export AWS_USE_DUALSTACK_ENDPOINT=true
fi
aws eks update-kubeconfig --name "$CLUSTER" --region "$REGION" >/dev/null
kubectl get nodes

echo "==> namespace + MLflow backend secret"
kubectl create namespace mlops --dry-run=client -o yaml | kubectl apply -f -
RDS_ENDPOINT="$(terraform -chdir="$TF_DIR" output -raw mlflow_db_endpoint)"  # host:port
kubectl create secret generic mlflow-db -n mlops \
  --from-literal=backend_uri="postgresql://mlflow:${TF_VAR_db_password}@${RDS_ENDPOINT}/mlflow" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "==> Argo Rollouts"
kubectl create namespace argo-rollouts --dry-run=client -o yaml | kubectl apply -f -
# --server-side: these CRD schemas blow past the 262144-byte annotation limit that
# client-side apply imposes via last-applied-configuration.
kubectl apply --server-side --force-conflicts -n argo-rollouts -f \
  https://github.com/argoproj/argo-rollouts/releases/latest/download/install.yaml

echo "==> kube-prometheus-stack (monitoring)"
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null 2>&1 || true
helm repo update >/dev/null
helm upgrade --install prom prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace \
  --set prometheus.prometheusSpec.retention=6h \
  --set prometheus.prometheusSpec.resources.requests.memory=512Mi \
  --set grafana.resources.requests.memory=128Mi \
  --set prometheus.prometheusSpec.podMonitorSelectorNilUsesHelmValues=false \
  --set prometheus.prometheusSpec.serviceMonitorSelectorNilUsesHelmValues=false \
  --wait --timeout 12m

echo "==> Argo CD"
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply --server-side --force-conflicts -n argocd -f \
  https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

echo "==> waiting for control planes to become ready"
kubectl rollout status deploy/argocd-server -n argocd --timeout=8m
kubectl rollout status deploy/argo-rollouts -n argo-rollouts --timeout=8m

cat <<EOF

Platform ready.
  Argo CD admin password:
    kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d
  Grafana admin password:
    kubectl -n monitoring get secret prom-grafana -o jsonpath='{.data.admin-password}' | base64 -d
EOF
