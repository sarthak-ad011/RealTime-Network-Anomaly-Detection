"""CLI training entry point.

Usage:
    python -m src.training.train --model lstm_ae --experiment v1 --epochs 20
    python -m src.training.train --model iforest --experiment v1
"""
from __future__ import annotations

import os
import pickle
from pathlib import Path

import mlflow
import mlflow.pytorch
import mlflow.sklearn
import torch
import typer
from loguru import logger

import src.log_config  # noqa: F401 — activate file logging
from src.data.loader import FEATURE_COLS, clean, load_raw, prepare
from src.data.validation import validate
from src.models.isolation_forest import IFConfig, IsolationForestDetector
from src.models.lstm_autoencoder import LSTMConfig, LSTMDetector

app = typer.Typer()
MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://localhost:5000")
MODEL_NAME = "network-anomaly-detector"


@app.command()
def main(model: str = typer.Option(...), experiment: str = "default",
         data_dir: Path = Path("data/raw"), epochs: int = 20, seed: int = 42):
    mlflow.set_tracking_uri(MLFLOW_URI)
    mlflow.set_experiment(experiment)
    with mlflow.start_run() as run:
        mlflow.log_params({"model": model, "seed": seed})
        df = clean(load_raw(data_dir))
        if not validate(df, FEATURE_COLS):
            raise RuntimeError("Data validation failed. Aborting.")
        bundle = prepare(df, seed=seed, benign_only_train=(model == "lstm_ae"))
        mlflow.log_metrics({
            "n_train": len(bundle.X_train), "n_test": len(bundle.X_test),
            "test_attack_ratio": float(bundle.y_test.mean()),
        })
        if model == "iforest":
            cfg = IFConfig()
            mlflow.log_params(cfg.__dict__)
            det = IsolationForestDetector(cfg).fit(bundle.X_train)
            metrics = det.evaluate(bundle.X_test, bundle.y_test)
            mlflow.log_metrics(metrics)
            mlflow.sklearn.log_model(det.model, "model", registered_model_name=MODEL_NAME)
        elif model == "lstm_ae":
            cfg = LSTMConfig(seq_len=len(FEATURE_COLS), epochs=epochs)
            mlflow.log_params({k: v for k, v in cfg.__dict__.items() if k != "device"})
            det = LSTMDetector(cfg).fit(bundle.X_train, bundle.X_val)
            metrics = det.evaluate(bundle.X_test, bundle.y_test)
            mlflow.log_metrics(metrics)
            ckpt = Path("checkpoints") / f"{run.info.run_id}.pt"
            ckpt.parent.mkdir(exist_ok=True)
            torch.save(det.state_dict(), ckpt)
            mlflow.log_artifact(str(ckpt), "model")
            scaler_path = Path("checkpoints") / f"{run.info.run_id}_scaler.pkl"
            with open(scaler_path, "wb") as f:
                pickle.dump(bundle.scaler, f)
            mlflow.log_artifact(str(scaler_path), "model")
            mlflow.pytorch.log_model(det.model, "pytorch_model", registered_model_name=MODEL_NAME)
        else:
            raise typer.BadParameter(f"Unknown model: {model}")
        logger.info(f"Run {run.info.run_id} done: {metrics}")


if __name__ == "__main__":
    app()