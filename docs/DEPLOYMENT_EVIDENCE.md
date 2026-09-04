# Deployment evidence

Captured from a live deployment of this stack on AWS EKS (`anomaly-dev`, ap-south-1),
2026-09-04. Everything below is copied from the running cluster — no reconstructed
output. The cluster is torn down between sessions; `terraform apply` rebuilds it.

---

## 1. Model results

Held-out 20% stratified test split of the full CIC-IDS2017 dataset — 565,553 flows,
19.7% attacks. The autoencoder trained on benign flows only.

| model | AUC-PR | AUC-ROC | precision | recall | F1 |
|---|---|---|---|---|---|
| LSTM autoencoder (champion, v1) | **0.6319** | 0.7727 | 0.9918 | 0.2528 | 0.4029 |
| Isolation Forest (baseline) | 0.3357 | 0.6633 | 0.0592 | 0.0030 | 0.0057 |
| LSTM 4-epoch (challenger, v2) | 0.5882 | 0.7039 | 0.9876 | 0.2489 | 0.3976 |

---

## 2. Canary gate — healthy deploy PASSES

`AnalysisRun anomaly-inference-578f4b756-6-2`. Both metrics scoped to the canary's
`rollouts_pod_template_hash`, so the analysis measures only canary pods rather than
averaging them in with the healthy stable fleet.

```
phase: Successful
  p99-latency        phase=Successful successful=4
    measurements: ['[0.00495]', '[0.00495]', '[0.00495]', '[0.00495]']
  anomaly-flag-rate  phase=Successful successful=4
    measurements: ['[0.06598984771573604]', '[0.06490872210953347]',
                   '[0.05583756345177665]', '[0.05679513184584179]']
```

Flag rate 5.6–6.6% against a 15% gate, p99 latency 4.95ms against a 200ms gate.

The same gate ran again on a real code change travelling the full pipeline — the drift
sampling fix in section 5, pushed to `main`, built by CI, tagged `fd80dbd`, pushed to
ECR, manifest bumped by the CI bot, synced by Argo CD, canaried and promoted with no
human touching the cluster (`AnalysisRun anomaly-inference-678b8544d8-9-2`):

```
anomaly-flag-rate  phase=Successful successful=4
  measurements: [0.04941860465116279] [0.05367168242570746]
                [0.05671175858480749] [0.057872784150156405]
p99-latency        phase=Successful successful=4
  measurements: [0.00495] [0.0049499999999999995] [0.0049499999999999995] [0.00495]
```

```
Status:  ✔ Healthy
Step:    8/8   SetWeight: 100   ActualWeight: 100
Images:  ...anomaly-mlops:fd80dbd (stable)
Replicas: Desired 4  Current 4  Updated 4  Ready 4  Available 4
```

---

## 3. Canary gate — deliberately broken deploy is CAUGHT and ROLLED BACK

The point of the ML-specific gate. A deploy was injected with
`ANOMALY_THRESHOLD_SCALE=0.0005`, which drops the detector's threshold far enough that
it flags almost every flow as an attack. The model stays **fast and healthy by every
infrastructure measure** — this is precisely the failure a latency/error-rate SLO
cannot see.

`AnalysisRun anomaly-inference-8dc9f6f89-7-2`:

```
p99-latency        phase=Successful  successful=2
  measurements: [0.0049499999999999995] [0.00495]
anomaly-flag-rate  phase=Failed      failed=2
  measurements: [0.9756476683937823] [0.975622406639004]
```

Latency was unchanged at 4.95ms. The flag rate hit **97.6% against the 15% gate**, and
Argo Rollouts aborted:

```
Status:  ✖ Degraded
Message: RolloutAborted: Rollout aborted update to revision 7:
         Step-based analysis phase error/failed:
         Metric "anomaly-flag-rate" assessed Failed due to failed (2) > failureLimit (1)
```

The canary ReplicaSet was scaled to zero and the stable fleet never dropped below full
capacity — **no downtime**:

```
├──# revision:7
│  ├──⧉ anomaly-inference-8dc9f6f89   ReplicaSet   • ScaledDown   canary
│  └──α anomaly-inference-8dc9f6f89-7-2  AnalysisRun  ✖ Failed     ✔ 2,✖ 2
├──# revision:6
│  ├──⧉ anomaly-inference-578f4b756   ReplicaSet   ✔ Healthy      stable
│  │  ├──□ anomaly-inference-578f4b756-5wkt6  Pod  ✔ Running  ready:1/1
│  │  ├──□ anomaly-inference-578f4b756-ms8pg  Pod  ✔ Running  ready:1/1
│  │  ├──□ anomaly-inference-578f4b756-xclsc  Pod  ✔ Running  ready:1/1
│  │  └──□ anomaly-inference-578f4b756-fct2k  Pod  ✔ Running  ready:1/1
```

Re-enabling Argo CD auto-sync then removed the injected variable and returned the
Rollout to `Healthy` / `Synced` on its own — the GitOps layer self-healing the cluster
back to what Git says.

> **Method note, stated for honesty:** Argo CD auto-sync was paused while the bad
> config was injected directly into the Rollout, rather than committing a knowingly
> broken manifest to `main`. What is demonstrated is the Argo Rollouts analysis gate
> and the Argo CD self-heal — not a bad commit travelling the full CI path.

---

## 4. Drift detection — negative control (in-distribution traffic)

Traffic replayed from the benign training distribution. No drift, as expected:

```
loaded 20000 recent predictions from 20000 objects
drift summary: {'number_of_columns': 15, 'number_of_drifted_columns': 4,
                'share_of_drifted_columns': 0.26666666666666666,
                'dataset_drift': False}
no significant drift
```

4 of 15 columns, share 0.267 against a 0.5 threshold.

## 5. Drift detection — positive test (covariate shift)

The load generator was switched to `--mode=drift`, which shifts the benign distribution
by up to 2.5 standard deviations per feature. This is *not* an attack — the traffic is
still benign, it simply no longer resembles what the model was trained on.

```
capping at the 2500 most recent of 89860 objects
loaded 2500 recent predictions from 2500 objects
drift summary: {'number_of_columns': 15, 'number_of_drifted_columns': 15,
                'share_of_drifted_columns': 1.0,
                'dataset_drift': True}
drift marker written: 15/15 columns drifted
```

Marker written to `s3://anomaly-mlops-artifacts-dev/drift/drift_detected.json`:

```json
{"detected_at": "2026-09-04T11:38:57.814429+00:00", "number_of_columns": 15,
 "number_of_drifted_columns": 15, "share_of_drifted_columns": 1.0,
 "dataset_drift": true}
```

**This test is what caught a real bug.** The `capping at the 2500 most recent of 89860`
line matters: the original `load_recent()` truncated S3's listing, which is
lexicographic, and prediction keys are UUIDs. It therefore sampled arbitrarily across
the whole window and would have averaged a genuine shift away against hours of
in-distribution backlog — silently failing to notice exactly the traffic a drift check
exists to notice. The fix keeps the newest objects instead.

---

## 6. Promotion gate — a worse challenger is REJECTED

```
champion  v1: auc_pr=0.6319 recall=0.2528 f1=0.4029
candidate v2: auc_pr=0.5882 recall=0.2489 f1=0.3976

PROMOTE: False  (AUC-PR insufficient: 0.5882 vs 0.6319)
candidate rejected; champion retained
```

---

## 7. GitOps and delivery

```
NAME            SYNC STATUS   HEALTH STATUS
anomaly-mlops   Synced        Healthy
```

CI/CD proven end to end: lint → test → keyless OIDC auth to AWS → build → push to ECR →
bot commit bumping the image tag in the manifest → Argo CD sync. Shadow deployment
(champion v1 serving, challenger v2 receiving mirrored traffic with predictions logged
but never returned) and IRSA pod credentials both confirmed working.

Analysis run history — the `Error` runs were configuration faults found and fixed
during bring-up (an unsupplied `canary-hash` argument, and a cold-start window where
`rate()` returned an empty vector); they are left here rather than trimmed:

```
NAME                                 STATUS       AGE
anomaly-inference-64cf87bf6b-4-2     Error        121m
anomaly-inference-757d6b6cc8-5-2     Error        41m
anomaly-inference-757d6b6cc8-5-2.1   Error        33m
anomaly-inference-757d6b6cc8-5-2.2   Error        29m
anomaly-inference-578f4b756-6-2      Successful   13m
anomaly-inference-8dc9f6f89-7-2      Failed       (section 3, deliberate)
```

---

## 8. Orchestration (Airflow)

Installed from `k8s/airflow/values.yaml` — chart 1.16.0, Airflow 2.10.5,
KubernetesExecutor, metadata in its own `airflow` database on the shared RDS instance.
DAGs arrive by git-sync from `main`, so a merge is the deploy.

```
dag_id                  | fileloc                                                          | owners | is_paused
========================+==================================================================+========+==========
anomaly_retraining_loop | /opt/airflow/dags/repo/pipelines/airflow/dags/retraining_loop.py | mlops  | True
```

git-sync tracking `main`:

```
msg="updated successfully" ref="main" remote="52f73bdc4b805e70fd36540d251de3e7284051e4" syncCount=1
```

A manual run of `anomaly_retraining_loop` executed `drift_check` as a real
`KubernetesPodOperator` — the executor launched a worker pod in `airflow`, which
launched the task pod in `mlops`, cross-namespace, on the fixed image:

```
dag_id                  | task_id      | state   | start_date                       | end_date
anomaly_retraining_loop | drift_check  | success | 2026-09-04T11:50:29.063724+00:00 | 2026-09-04T11:51:16.567992+00:00
```

**The next task then failed, and the failure was worth more than the success.** The
`branch` step reads the drift marker from S3 *inside the Airflow scheduler*, not in a
task pod, and it raised:

```
botocore.exceptions.NoCredentialsError: Unable to locate credentials
```

The assumption behind the original setup was that a pod without IRSA falls back to the
node role over IMDS — the node role does carry S3 access. It does not: this node group
restricts the IMDS hop limit, so pods cannot reach it at all. Everything that had ever
worked in this cluster ran as `anomaly-sa`, which has IRSA, so the assumption was never
tested until Airflow's own pods needed AWS.

Two things changed as a result:

1. The IRSA trust policy now names the Airflow service accounts alongside `anomaly-sa`
   (`terraform/modules/iam/main.tf`), rather than widening the node role.
2. Task logs now ship to S3. Under KubernetesExecutor the worker pod is deleted the
   moment a task ends, so this failure's log was already gone by the time anyone looked
   at it — the diagnosis above had to be reproduced by hand in the scheduler. That is
   not a workable position for a pipeline that retrains unattended every six hours.

### After both fixes

The scheduler now assumes the IRSA role rather than finding no credentials:

```
identity: arn:aws:sts::170420138680:assumed-role/anomaly-mlops-irsa-dev/botocore-session-1788525548
marker:   {'detected_at': '2026-09-04T11:51:13.423493+00:00', 'number_of_columns': 15,
           'number_of_drifted_columns': 15, 'share_of_drifted_columns': 1.0,
           'dataset_drift': True}
age: 0:47:55 -> RESULT: retrain
```

That marker timestamp is worth reading twice: `11:51:13` is the *in-cluster*
`drift_check` task writing it, not the local run in section 5. Drift detection ran end
to end inside the cluster on the fixed image.

Run `evidence-run-1` then reached the branch decision:

```
task_id      | state
drift_check  | success
branch       | success
skip         | skipped      <- branch chose the retraining path, not skip
retrain      | failed
```

And task logs now survive their pods:

```
airflow-logs/dag_id=anomaly_retraining_loop/run_id=evidence-run-1/task_id=drift_check/attempt=1.log
airflow-logs/dag_id=anomaly_retraining_loop/run_id=evidence-run-1/task_id=branch/attempt=1.log
airflow-logs/dag_id=anomaly_retraining_loop/run_id=evidence-run-1/task_id=retrain/attempt=1.log
```

### The retrain leg does not run here, and this is why

`retrain` fails, deliberately reported rather than hidden:

```
FileNotFoundError: No CSVs in data/raw
airflow.exceptions.AirflowException: Pod retrain-sgz6hdhi returned a failure.
```

`src/data/loader.py:load_raw()` globs a local directory. The 844MB CIC-IDS2017 CSVs are
not baked into the image and are not staged in S3, so the task pod has nothing to train
on. Closing this means uploading the raw data and teaching the loader to read `s3://` —
it is the first item on the roadmap. Every stage up to and including the branch decision
is live; the retrain and promote legs are wired but unexercised in this deployment.

---

## 9. Environment

- AWS account `170420138680`, region `ap-south-1`
- EKS `anomaly-dev`, Kubernetes 1.33, 2× `m7i-flex.large`
- ECR `170420138680.dkr.ecr.ap-south-1.amazonaws.com/anomaly-mlops`
- RDS `mlflow-dev` (Postgres 16.13) — MLflow backend store + Airflow metadata
- S3 `anomaly-mlops-artifacts-dev` — MLflow artifacts, prediction log, drift markers
- IRSA role `anomaly-mlops-irsa-dev`, assumable only by
  `system:serviceaccount:mlops:anomaly-sa`

Running cost is roughly $8–10/day, so the stack is destroyed between sessions and
rebuilt with `terraform apply`. That is only survivable because Git is the source of
truth: Argo CD reconstitutes the workloads, and the artifacts outlive the cluster in
S3 and RDS.
