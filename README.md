# Network Anomaly Detection — MLOps Platform

End-to-end MLOps platform that detects anomalous network traffic in real time and **retrains itself when the data drifts**. An LSTM autoencoder trained on CIC-IDS2017 is served on AWS EKS through a full GitOps pipeline: push code, and it lint/tests, builds an image, pushes to ECR, and progressively rolls out to the cluster with automated rollback — while a drift detector watches production traffic and triggers gated retraining when the model goes stale.

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/python-3.11-blue" />
  <img alt="PyTorch" src="https://img.shields.io/badge/PyTorch-2.3-ee4c2c" />
  <img alt="AWS EKS" src="https://img.shields.io/badge/AWS-EKS-ff9900" />
  <img alt="Terraform" src="https://img.shields.io/badge/IaC-Terraform-7b42bc" />
  <img alt="Argo CD" src="https://img.shields.io/badge/GitOps-Argo%20CD-ef7b4d" />
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green" />
</p>


---

## Why this project

Most anomaly detectors are trained once and silently decay as attack patterns and traffic evolve. This platform closes that loop: it detects when its own predictions drift, retrains on recent data, and promotes the new model **only if it beats the current one without regressing recall** — because in security, a missed attack costs more than a false alarm. The whole system is infrastructure-as-code and reproducible from scratch in ~25 minutes.

It's deliberately built at the intersection of ML and platform engineering — training a non-trivial model *and* wrapping it in the production machinery (GitOps, progressive delivery, drift-triggered retraining) that real ML teams run.

---

## Architecture

```
                          ┌─────────────── GitHub ───────────────┐
   git push ─────────────▶│  Actions CI: ruff → pytest → build    │
                          │  → push image to ECR → bump manifest  │
                          └──────────────────┬────────────────────┘
                                             │ commit (new image tag)
                                             ▼
                          ┌──────────── Argo CD (GitOps) ─────────┐
                          │  reconciles cluster state from Git    │
                          └──────────────────┬────────────────────┘
                                             ▼
   ┌─────────────────────────────── AWS EKS ────────────────────────────────┐
   │                                                                        │
   │   Argo Rollouts canary: 10% → analysis → 30% → 60% → 100%              │
   │        │                      │                                        │
   │        │        Prometheus analysis fails → auto-rollback              │
   │        ▼                                                               │
   │   ┌──────────────┐   champion   ┌─────────────────────┐                │
   │   │  FastAPI     │─────────────▶│ LSTM Autoencoder     │──▶ prediction  │
   │   │  inference   │   shadow     ├─────────────────────┤                │
   │   │  service     │─────────────▶│ candidate (logged)   │                │
   │   └──────┬───────┘              └─────────────────────┘                │
   │          │ every prediction → S3                                       │
   │          ▼                                                             │
   │   ┌──────────────┐   drift > τ   ┌─────────────────────┐               │
   │   │ Evidently    │──────────────▶│ Airflow retrain DAG  │               │
   │   │ drift job    │               │ → gated promotion    │               │
   │   └──────────────┘               └─────────┬───────────┘               │
   │                                            ▼                           │
   │   MLflow registry  ◀── promote if AUC-PR↑ and recall not regressed     │
   │   Prometheus + Grafana ◀── latency, score dist, shadow disagreement    │
   └────────────────────────────────────────────────────────────────────────┘
```

---

## Tech stack

| Layer | Tools |
|-------|-------|
| **Modeling** | PyTorch (LSTM autoencoder), scikit-learn (Isolation Forest baseline) |
| **Experiment tracking** | MLflow (tracking + model registry with champion/challenger stages) |
| **Data versioning** | DVC |
| **Serving** | FastAPI, Docker |
| **Infrastructure** | Terraform, AWS EKS, ECR, RDS, S3, IAM |
| **CI/CD** | GitHub Actions, keyless AWS auth via OIDC |
| **GitOps & delivery** | Argo CD, Argo Rollouts (canary + metric-gated rollback) |
| **Monitoring** | Prometheus, Grafana |
| **Drift & retraining** | Evidently, Apache Airflow |

---

## Key features

- **LSTM autoencoder** trained on benign-only traffic — flags anomalies by reconstruction error, so it generalizes to novel attacks a supervised classifier would miss. Benchmarked against an Isolation Forest baseline.
- **Shadow deployment** — a candidate model receives mirrored production traffic with predictions logged, never served, so new models are validated on real data before promotion.
- **Progressive delivery** — new versions canary through 10 → 30 → 60 → 100% of traffic, gated at each step by Prometheus analysis, with automatic rollback on regression.
- **ML-aware rollback** — beyond latency/error SLOs, the canary checks the live **prediction distribution**, catching behaviorally broken models (e.g. one that flags everything) that would pass standard infra checks.
- **Self-healing loop** — Evidently detects drift on the live prediction stream → Airflow retrains → a promotion gate ships the new model only if AUC-PR improves and recall doesn't regress.
- **GitOps everywhere** — every deploy is an auditable Git commit; the cluster is disposable because Git is the source of truth.
- **Fully reproducible** — `terraform apply` stands up the entire stack (EKS, ECR, RDS, S3, IAM, OIDC) from zero.

---

## Repository layout

```
network-anomaly-mlops/
├── notebooks/01_train_models.ipynb   # EDA + training (start here)
├── src/
│   ├── data/                         # loading, cleaning, validation
│   ├── models/                       # Isolation Forest + LSTM autoencoder
│   ├── training/                     # training CLI + champion/challenger gate
│   ├── serving/                      # FastAPI app (champion + shadow) + Dockerfile
│   └── drift/                        # Evidently drift job
├── terraform/                        # EKS, ECR, RDS, S3, IAM, GitHub OIDC
├── k8s/                              # Kustomize manifests, Argo CD app, Rollout
├── pipelines/airflow/dags/           # drift → retrain → promote DAG
├── traffic_generator/                # synthetic normal/attack/drift traffic
├── tests/                            # model + promotion-gate unit tests
└── .github/workflows/cicd.yaml       # CI/CD pipeline
```

---

## Quickstart (local — no cloud, no cost)

Train the model and serve it on your laptop first. This needs no AWS account.

```bash
# 1. Setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Get the dataset (CIC-IDS2017) into data/raw/
#    Kaggle: search "CIC-IDS2017" (MachineLearningCSV variant), or use the
#    official UNB source. See docs for details.
./scripts/download_data.sh

# 3. Start MLflow locally
mlflow server --backend-store-uri sqlite:///mlflow.db --port 5000 &

# 4. Train (notebook or CLI)
jupyter notebook notebooks/01_train_models.ipynb        # exploratory
python -m src.training.train --model lstm_ae --experiment v1 --epochs 20

# 5. Serve + test
uvicorn src.serving.app:app --reload
curl -X POST localhost:8000/predict -H 'Content-Type: application/json' \
  -d '{"features":[1500000,12,10,250,200,5000,50,100000,50000,50000,220,180,0.1,5,230]}'

# 6. Run the tests
pytest tests/ -v
```

---

## Deploy to AWS

The full cloud deployment is documented step by step — infrastructure, GitOps, CI/CD, monitoring, and the retraining loop — in **[`MASTER_PLAN_FULL.md`](MASTER_PLAN_FULL.md)**. High level:

```bash
# Provision everything (EKS, ECR, RDS, S3, IAM, OIDC)
cd terraform/environments/dev
export TF_VAR_db_password='<a-strong-password>'
export TF_VAR_github_repo='<your-username>/network-anomaly-mlops'
terraform init && terraform apply           # ~25 min

# Point kubectl at the cluster
aws eks update-kubeconfig --name anomaly-dev --region ap-south-1

# Argo CD then syncs the app from Git; CI/CD ships new versions on every push.
```

> **Cost note:** running 24/7 is roughly $5–6/day (EKS control plane + nodes + NAT + RDS). `terraform destroy` drops it to near-zero — tear down between sessions and bring it back with `terraform apply` when needed.

---

## Model

The core model is an **LSTM autoencoder** trained only on benign network flows. It learns to reconstruct normal traffic; the reconstruction error becomes the anomaly score, with the threshold set at the 95th percentile of validation errors. This unsupervised framing means it flags attack types it never saw in training — a key advantage over a supervised classifier on a dataset where attacks are <1% of traffic.

An **Isolation Forest** serves as the baseline. The training pipeline logs both to MLflow with full metrics (AUC-PR, recall, precision, F1) so promotion decisions are grounded in the metric that matters for imbalanced anomaly detection: **AUC-PR**, not accuracy.

---

## Dataset

[CIC-IDS2017](https://www.unb.ca/cic/datasets/ids-2017.html) from the Canadian Institute for Cybersecurity — ~2.8M labeled network flows including DDoS, brute force, port scans, web attacks, and infiltration. The data is versioned with DVC and is not committed to the repo (see `.gitignore`).

---

## Testing

```bash
pytest tests/ -v
```

Unit tests cover the model interfaces (Isolation Forest + LSTM autoencoder fit/predict/evaluate) and every branch of the champion/challenger promotion gate — the critical code that decides whether a new model reaches production.

---

## Roadmap

- [ ] Swap synthetic traffic for replayed PCAP / eBPF flow data
- [ ] Graph neural network over pod-to-pod traffic
- [ ] Exact traffic splitting via service mesh (currently pod-ratio based)
- [ ] Analyst-in-the-loop label feedback into retraining
- [ ] Multi-armed bandit routing instead of all-or-nothing promotion

---

## License

MIT — see [LICENSE](LICENSE).