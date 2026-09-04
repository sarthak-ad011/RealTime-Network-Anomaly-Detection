#!/usr/bin/env bash
# Snapshot the running platform: cluster state, GitOps sync status, rollout
# position, and the live Prometheus series behind the canary gate.
# Writes a single markdown report to stdout (redirect it where you want it).
set -uo pipefail

PROM_NS="${PROM_NS:-monitoring}"
PROM_SVC="${PROM_SVC:-prom-kube-prometheus-stack-prometheus}"

section() { printf '\n## %s\n\n```\n' "$1"; }
endsec() { printf '```\n'; }

printf '# Platform evidence — %s\n' "$(date -u +'%Y-%m-%d %H:%M:%SZ')"

section "Nodes"
kubectl get nodes -o wide 2>&1
endsec

section "Pods (all namespaces)"
kubectl get pods -A 2>&1
endsec

section "Argo CD application"
kubectl get application -n argocd -o wide 2>&1
endsec

section "Argo Rollouts status"
kubectl argo rollouts get rollout anomaly-inference -n mlops --no-color 2>&1 \
  || kubectl get rollout anomaly-inference -n mlops -o wide 2>&1
endsec

section "AnalysisRuns (canary gate results)"
kubectl get analysisrun -n mlops 2>&1
endsec

section "MLflow registered models"
kubectl exec -n mlops deploy/mlflow -- \
  python -c "
from mlflow.tracking import MlflowClient
c = MlflowClient('http://localhost:5000')
for v in c.search_model_versions(\"name='network-anomaly-detector'\"):
    print(f'v{v.version}  stage={v.current_stage}  run={v.run_id[:12]}')
" 2>&1
endsec

# Query Prometheus from inside the cluster so no port-forward is needed.
prom_query() {
  kubectl run promq-$RANDOM -n "$PROM_NS" --rm -i --restart=Never \
    --image=curlimages/curl:8.10.1 --quiet -- \
    curl -sG "http://${PROM_SVC}.${PROM_NS}.svc.cluster.local:9090/api/v1/query" \
    --data-urlencode "query=$1" 2>/dev/null
}

section "Prometheus — inference series"
for q in \
  'sum(anomaly_predictions_total)' \
  'sum by (role) (anomaly_predictions_total)' \
  'sum by (role,is_anomaly) (anomaly_predictions_total)' \
  'histogram_quantile(0.99, sum by (le) (rate(anomaly_prediction_latency_seconds_bucket[5m])))' \
  'sum(anomaly_shadow_disagreement_total)'
do
  printf '%s\n  -> %s\n\n' "$q" "$(prom_query "$q")"
done
endsec
