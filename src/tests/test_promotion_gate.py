"""Tests for the promotion gate. Critical code — test every branch."""
from src.training.evaluate import should_promote


def test_promote_when_no_champion():
    ok, _ = should_promote({"auc_pr": 0.5, "recall": 0.6, "f1": 0.55}, None)
    assert ok


def test_promote_when_clear_improvement():
    champ = {"auc_pr": 0.50, "recall": 0.60, "f1": 0.55}
    cand = {"auc_pr": 0.55, "recall": 0.62, "f1": 0.58}
    ok, _ = should_promote(cand, champ)
    assert ok


def test_reject_when_aucpr_marginal():
    champ = {"auc_pr": 0.50, "recall": 0.60, "f1": 0.55}
    cand = {"auc_pr": 0.505, "recall": 0.65, "f1": 0.60}
    ok, reason = should_promote(cand, champ)
    assert not ok and "AUC-PR" in reason


def test_reject_when_recall_drops():
    champ = {"auc_pr": 0.50, "recall": 0.80, "f1": 0.65}
    cand = {"auc_pr": 0.55, "recall": 0.70, "f1": 0.62}
    ok, reason = should_promote(cand, champ)
    assert not ok and "recall" in reason


def test_reject_when_f1_drops():
    champ = {"auc_pr": 0.50, "recall": 0.60, "f1": 0.65}
    cand = {"auc_pr": 0.55, "recall": 0.62, "f1": 0.60}
    ok, reason = should_promote(cand, champ)
    assert not ok and "F1" in reason