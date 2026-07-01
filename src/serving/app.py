"""FastAPI inference service with shadow deployment.

Champion serves live predictions; shadow gets the same input but its predictions
are only logged (never returned). Both emit Prometheus metrics. Every prediction
is logged to S3 for drift detection.
"""
from __future__ import annotations

import src.log_config  # noqa: F401 — activate file logging

import asyncio
import json
import os
import pickle
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import boto3
import mlflow
import numpy as np
import torch
from fastapi import FastAPI, HTTPException
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
from pydantic import BaseModel, Field
from starlette.responses import Response

from src.data.loader import FEATURE_COLS
from src.models.lstm_autoencoder import LSTMAutoencoder, LSTMConfig

MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://127.0.0.1:5000")
MODEL_NAME = "network-anomaly-detector"
PREDICTION_BUCKET = os.getenv("PREDICTION_BUCKET", "anomaly-mlops-artifacts-dev")

s3 = boto3.client("s3")

PREDICTION_COUNTER = Counter("anomaly_predictions_total", "Predictions", ["role", "is_anomaly"])
PREDICTION_LATENCY = Histogram("anomaly_prediction_latency_seconds", "Latency", ["role"])
SCORE_HISTOGRAM = Histogram("anomaly_score", "Score distribution", ["role"],
                            buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0])
SHADOW_DISAGREEMENT = Counter("anomaly_shadow_disagreement_total", "Champion/shadow disagreement")


class PredictionRequest(BaseModel):
    features: list[float] = Field(..., min_length=15, max_length=15)


class PredictionResponse(BaseModel):
    request_id: str
    is_anomaly: bool
    score: float
    threshold: float
    model_version: str
    latency_ms: float


class LoadedModel:
    def __init__(self, model, scaler, threshold, version):
        self.model, self.scaler, self.threshold, self.version = model, scaler, threshold, version
        self.model.eval()

    @torch.no_grad()
    def predict(self, features):
        x = np.array(features, dtype=np.float32).reshape(1, -1)
        x_scaled = self.scaler.transform(x)
        seq = torch.tensor(x_scaled, dtype=torch.float32).unsqueeze(-1)
        recon = self.model(seq)
        err = ((recon - seq) ** 2).mean().item()
        return err > self.threshold, err


def load_from_mlflow(stage):
    mlflow.set_tracking_uri(MLFLOW_URI)
    client = mlflow.tracking.MlflowClient()
    versions = client.search_model_versions(
        f"name='{MODEL_NAME}'",
    )
    versions = [v for v in versions if v.current_stage == stage]
    if not versions:
        return None
    v = max(versions, key=lambda v: int(v.version))
    local = client.download_artifacts(v.run_id, "model")
    pt = next(Path(local).glob("*.pt"), None)
    scaler_p = next(Path(local).glob("*_scaler.pkl"), None)
    if pt is None or scaler_p is None:
        return None
    state = torch.load(pt, map_location="cpu")
    cfg = LSTMConfig(**{k: val for k, val in state["cfg"].items() if k != "device"})
    model = LSTMAutoencoder(cfg)
    model.load_state_dict(state["model"])
    with open(scaler_p, "rb") as f:
        scaler = pickle.load(f)
    return LoadedModel(model, scaler, state["threshold"], v.version)


class AppState:
    champion = None
    shadow = None


state = AppState()


@asynccontextmanager
async def lifespan(app):
    state.champion = load_from_mlflow("Production")
    state.shadow = load_from_mlflow("Staging")
    if state.champion is None:
        raise RuntimeError("No Production model in MLflow")
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "champion_version": state.champion.version if state.champion else None,
        "shadow_version": state.shadow.version if state.shadow else None,
    }


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


async def _run_shadow(features, champion_label):
    if state.shadow is None:
        return
    start = time.perf_counter()
    label, score = state.shadow.predict(features)
    PREDICTION_COUNTER.labels("shadow", str(int(label))).inc()
    PREDICTION_LATENCY.labels("shadow").observe(time.perf_counter() - start)
    SCORE_HISTOGRAM.labels("shadow").observe(score)
    if label != champion_label:
        SHADOW_DISAGREEMENT.inc()


async def _log_prediction(record):
    key = f"predictions/{record['date']}/{record['request_id']}.json"
    await asyncio.to_thread(s3.put_object, Bucket=PREDICTION_BUCKET, Key=key,
                            Body=json.dumps(record).encode())


@app.post("/predict", response_model=PredictionResponse)
async def predict(req: PredictionRequest):
    if state.champion is None:
        raise HTTPException(503, "Model not loaded")
    request_id = str(uuid.uuid4())
    start = time.perf_counter()
    label, score = state.champion.predict(req.features)
    latency = time.perf_counter() - start
    PREDICTION_COUNTER.labels("champion", str(int(label))).inc()
    PREDICTION_LATENCY.labels("champion").observe(latency)
    SCORE_HISTOGRAM.labels("champion").observe(score)
    now = datetime.now(timezone.utc)
    record = {
        "request_id": request_id, "timestamp": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"), "features": req.features,
        "feature_names": FEATURE_COLS,
        "champion": {"version": state.champion.version, "score": score,
                     "label": int(label), "threshold": state.champion.threshold},
    }
    asyncio.create_task(_run_shadow(req.features, label))
    asyncio.create_task(_log_prediction(record))
    return PredictionResponse(
        request_id=request_id, is_anomaly=label, score=score,
        threshold=state.champion.threshold, model_version=state.champion.version,
        latency_ms=latency * 1000)