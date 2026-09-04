# 3-minute demo — shot list

Recording plan for the walkthrough video. Times are the target length of each cut, not
how long the step takes live: several steps run for 6–10 minutes and get trimmed hard.
Record everything, cut afterwards.

**Record with:** QuickTime (⌘⇧5, "Record Selected Portion") or OBS. Four browser
windows tiled 2×2 on one screen reads better than tab-switching.

---

## Setup before you hit record

Port-forwards (each in its own terminal, or let the assistant start them):

```bash
kubectl -n monitoring port-forward svc/prom-grafana 3001:80
kubectl -n argocd     port-forward svc/argocd-server 8082:443
kubectl -n airflow    port-forward svc/airflow-webserver 8080:8080
kubectl -n mlops      port-forward svc/mlflow 5001:5000
```

| Window | URL | Login | Show |
|---|---|---|---|
| top-left | http://localhost:3001/d/anomaly-inference | `admin` / your password | flag rate + score distribution |
| top-right | https://localhost:8082 | `admin` / see cluster secret | application tree, Synced/Healthy |
| bottom-left | http://localhost:8080 | `admin` / `admin` | `anomaly_retraining_loop` graph view |
| bottom-right | http://localhost:5001 | none | Models → `network-anomaly-detector`, v1 Production / v2 Staging |

Argo CD is **HTTPS on 8082** — it redirect-loops over plain HTTP. Accept the
self-signed certificate once before recording so the warning page isn't in the cut.

---

## Shot 1 — the platform, at rest (0:00–0:20)

Slow pan across the four windows. Argo CD `Synced / Healthy`, 4 inference replicas,
MLflow showing champion v1 in Production and challenger v2 in Staging.

> "An LSTM autoencoder detecting network intrusions on EKS — GitOps delivery,
> progressive rollout, drift-triggered retraining. Everything here is reconstructible
> from Git with one `terraform apply`."

## Shot 2 — baseline traffic (0:20–0:40)

```bash
kubectl -n mlops scale deploy loadgen --replicas=1     # runs in --mode=attack
```

Hold on Grafana until the flag rate settles around **5–6%** and the score histogram
forms a stable shape. This is the reference the next shot is measured against.

> "Normal traffic, ~6% flagged as anomalous. That number is the thing worth watching."

## Shot 3 — drift (0:40–1:15)

The assistant switches the generator to covariate-shift mode — same benign traffic,
shifted up to 2.5 standard deviations per feature:

```bash
kubectl -n mlops patch deploy loadgen --type=json -p '[{"op":"replace","path":"/spec/template/spec/containers/0/args","value":[
  "--endpoint=http://anomaly-inference-stable.mlops.svc.cluster.local",
  "--mode=drift","--rps=25","--drift-minutes=2",
  "--reference=s3://anomaly-mlops-artifacts-dev/reference/training_reference.parquet"]}]'
```

Stay on Grafana. Over ~2 minutes the flag rate climbs from 6% toward 80%+ and the
score distribution visibly slides right. **Trim this to ~15s of timelapse.**

> "The traffic is still benign. It just stopped looking like what the model was trained
> on — and the model's behaviour changes underneath us."

## Shot 4 — drift is detected (1:15–1:50)

Airflow window. Trigger the DAG, then open `drift_check` → Logs:

```bash
kubectl -n airflow exec deploy/airflow-scheduler -c scheduler -- \
  airflow dags trigger anomaly_retraining_loop
```

The log line to land on:

```
drift summary: {'number_of_columns': 15, 'number_of_drifted_columns': 15,
                'share_of_drifted_columns': 1.0, 'dataset_drift': True}
drift marker written: 15/15 columns drifted
```

Then show the graph view: `drift_check` green → `branch` green → routed to **`retrain`**,
with `skip` greyed out.

> "Evidently scores all 15 features against the training reference. All 15 drifted, the
> job writes a marker to S3, and the DAG branches toward retraining rather than
> skipping."

**Say this out loud — do not skip it:**

> "The retrain task itself needs the raw dataset staged in S3, which isn't done in this
> deployment — so that leg is wired but not exercised here. Everything up to the
> branch decision is live."

## Shot 5 — a broken model is caught and rolled back (1:50–2:40)

The strongest 50 seconds in the video. The assistant deploys a model that is *fast and
healthy by every infrastructure measure* but behaviourally broken:

```bash
kubectl -n argocd patch application anomaly-mlops --type=merge \
  -p '{"spec":{"syncPolicy":{"automated":null}}}'          # pause auto-sync
kubectl -n mlops scale deploy loadgen-canary --replicas=1  # canary needs traffic
kubectl -n mlops patch rollout anomaly-inference --type=json \
  -p '[{"op":"add","path":"/spec/template/spec/containers/0/env/-",
        "value":{"name":"ANOMALY_THRESHOLD_SCALE","value":"0.0005"}}]'
```

Watch in a terminal (this is the money shot — record the terminal, not just the UI):

```bash
kubectl argo rollouts get rollout anomaly-inference -n mlops --watch
```

Takes ~6 minutes live: canary at 10% → 2m pause → analysis → abort. **Trim to ~40s.**
Land on:

```
Status:  ✖ Degraded
Message: RolloutAborted: ... Metric "anomaly-flag-rate" assessed Failed
         due to failed (2) > failureLimit (1)
```

Cut to the AnalysisRun numbers — latency fine, behaviour broken:

```
p99-latency        Successful   [0.00495] [0.00495]
anomaly-flag-rate  Failed       [0.9756]  [0.9756]
```

> "Latency never moved — 5 milliseconds, well inside SLO. A latency-and-error-rate gate
> would have shipped this. The canary also checks the *prediction distribution*: 97.6%
> of traffic flagged against a 15% limit. Rollout aborted, canary scaled to zero, and
> the stable fleet never dropped below four healthy replicas. No downtime."

Then restore and show GitOps self-heal:

```bash
kubectl -n argocd patch application anomaly-mlops --type=merge \
  -p '{"spec":{"syncPolicy":{"automated":{"prune":true,"selfHeal":true}}}}'
```

Argo CD removes the injected variable on its own and returns to `Synced / Healthy`.

> "And Argo CD puts the cluster back to what Git says, without being asked."

## Shot 6 — close (2:40–3:00)

Back to the four windows, everything green.

> "Drift detection, a canary gate that understands the model and not just the pod, and
> automatic rollback — on infrastructure that rebuilds from scratch with one command."

---

## Cleanup after recording

```bash
kubectl -n mlops scale deploy loadgen --replicas=0
kubectl -n mlops scale deploy loadgen-canary --replicas=0
```

Then tear the stack down — every prediction is an S3 PUT and the cluster is ~$0.34/hr:

```bash
cd terraform/environments/dev
source ~/.anomaly-mlops-dev.env      # TF_VAR_db_password is REQUIRED by destroy

# APPLY FIRST — this is not optional, and it is the step that gets skipped.
#
# The artifacts bucket and the ECR repo are never empty at teardown: a single demo
# afternoon leaves >100k prediction objects (plus a version each, because versioning
# is on) and CI pushes one image per commit. Neither resource deletes while
# non-empty, so the modules set force_destroy / force_delete.
#
# But Terraform reads force_destroy from STATE, not from the configuration, when it
# builds a destroy plan. Editing the .tf file is not enough — the flag has to be
# applied into state first. Skip this apply and destroy fails with:
#
#   Error deleting S3 Bucket (anomaly-mlops-artifacts-dev): BucketNotEmpty:
#   The bucket you tried to delete is not empty. You must delete all versions.
#
# Terraform then continues destroying everything else and exits non-zero at the end,
# which is the worst shape to be in: most of the stack gone, the state file now
# describing a bucket that still exists, and no clear signal about what is left
# running. This happened on 2026-09-04 and the cleanup had to be finished by hand
# in the console.
terraform apply -auto-approve        # no infrastructure change; lands the flags in state
terraform destroy -auto-approve
```

Verify nothing survived, rather than trusting the exit code:

```bash
aws eks list-clusters --region ap-south-1                 # expect: []
aws rds describe-db-instances --region ap-south-1 \
  --query 'DBInstances[].DBInstanceIdentifier'            # expect: []
aws ec2 describe-nat-gateways --region ap-south-1 \
  --query 'NatGateways[?State==`available`].NatGatewayId'  # expect: []
aws ec2 describe-instances --region ap-south-1 \
  --query 'Reservations[].Instances[?State.Name==`running`].InstanceId'
aws s3 ls | grep anomaly                                  # only the tfstate bucket
```

Query AWS directly like this rather than trusting terraform's exit code or its state
file — if destroy failed partway, state is exactly the thing that is now wrong.

The NAT gateway and the EKS control plane are the two line items that keep charging
whether or not anything is running on them — check those two even if you check nothing
else.

The `anomaly-mlops-tfstate` bucket is meant to survive: it holds the state file that
makes the next `terraform apply` reproducible, and costs a few cents a month. It is
easy to sweep up by accident when clearing buckets by hand. If it is gone, recreate it
before anything else — `terraform init` cannot configure its backend without it:

```bash
aws s3api create-bucket --bucket anomaly-mlops-tfstate --region ap-south-1 \
  --create-bucket-configuration LocationConstraint=ap-south-1
aws s3api put-bucket-versioning --bucket anomaly-mlops-tfstate \
  --versioning-configuration Status=Enabled

cd terraform/environments/dev
terraform init -reconfigure
```

Losing it is recoverable but not free: terraform starts from an empty state, so it
knows about nothing that already exists. That is fine after a clean teardown and
actively dangerous after a partial one — verify with the AWS queries above that the
account really is empty before applying into a blank state, or you will get a second
copy of anything that survived.

---

## Honesty checklist

Claims the footage actually supports, and the one it does not:

- ✅ Drift detected on live production traffic, 15/15 columns, marker written to S3
- ✅ Airflow branches on that marker toward retraining
- ✅ Canary gate catches a behaviourally broken model that passes every infra check
- ✅ Automatic rollback with no downtime; Argo CD self-heals the config
- ✅ Full CI → ECR → Argo CD → canary → promote on a real code change
- ❌ **Not shown:** the retrain and promote legs executing. They need the 844MB
  CIC-IDS2017 dataset staged in S3 and a loader that reads `s3://`. Say so on camera.
