"""Smoke tests for the model interfaces. Fast, no GPU or real data needed."""
import numpy as np
import pytest

from src.models.isolation_forest import IsolationForestDetector, IFConfig
from src.models.lstm_autoencoder import LSTMDetector, LSTMConfig


@pytest.fixture
def synthetic_data():
    rng = np.random.default_rng(42)
    benign = rng.normal(0, 1, size=(500, 15)).astype(np.float32)
    attack = rng.normal(5, 2, size=(50, 15)).astype(np.float32)
    X_train = benign[:300]
    X_val = benign[300:400]
    X_test = np.vstack([benign[400:], attack])
    y_test = np.concatenate([np.zeros(100), np.ones(50)]).astype(np.int64)
    return X_train, X_val, X_test, y_test


def test_iforest_fit_predict(synthetic_data):
    X_train, _, X_test, y_test = synthetic_data
    det = IsolationForestDetector(IFConfig(n_estimators=50)).fit(X_train)
    preds = det.predict(X_test)
    assert preds.shape == (len(X_test),)
    assert set(preds.tolist()) <= {0, 1}
    m = det.evaluate(X_test, y_test)
    assert 0 <= m["auc_roc"] <= 1


def test_lstm_ae_fit_predict(synthetic_data):
    X_train, X_val, X_test, y_test = synthetic_data
    det = LSTMDetector(LSTMConfig(seq_len=15, epochs=2, batch_size=64)).fit(X_train, X_val)
    preds = det.predict(X_test)
    assert preds.shape == (len(X_test),)
    assert det.threshold is not None
    m = det.evaluate(X_test, y_test)
    assert m["auc_roc"] > 0.7


def test_lstm_ae_state_dict(synthetic_data):
    X_train, X_val, _, _ = synthetic_data
    det = LSTMDetector(LSTMConfig(seq_len=15, epochs=1)).fit(X_train, X_val)
    state = det.state_dict()
    assert "model" in state and "cfg" in state and "threshold" in state