"""Champion/challenger promotion gate. Prevents bad models from auto-deploying."""
from __future__ import annotations

import os
from loguru import logger

MLFLOW_URI = os.getenv("MLFLOW_TRACKING_URI", "http://mlflow.mlops:5000")
MODEL_NAME = "network-anomaly-detector"


def should_promote(candidate, champion, min_improvement=0.01, recall_tolerance=0.02):
    """Promote only if AUC-PR improves AND recall doesn't regress AND F1 holds."""
    if champion is None:
        return True, "no champion — promoting"
    if candidate["auc_pr"] < champion["auc_pr"] + min_improvement:
        return False, f"AUC-PR insufficient: {candidate['auc_pr']:.4f} vs {champion['auc_pr']:.4f}"
    if candidate["recall"] < champion["recall"] - recall_tolerance:
        return False, f"recall regressed: {candidate['recall']:.4f} vs {champion['recall']:.4f}"
    if candidate["f1"] < champion["f1"]:
        return False, f"F1 regressed: {candidate['f1']:.4f} vs {champion['f1']:.4f}"
    return True, "all gates passed"


def promote(candidate_run_id: str) -> bool:
    import mlflow
    from mlflow.tracking import MlflowClient
    mlflow.set_tracking_uri(MLFLOW_URI)
    client = MlflowClient()
    cand = client.get_run(candidate_run_id).data.metrics
    prod = client.get_latest_versions(MODEL_NAME, stages=["Production"])
    champ = client.get_run(prod[0].run_id).data.metrics if prod else None
    ok, reason = should_promote(cand, champ)
    logger.info(f"promote? {ok} ({reason})")
    if not ok:
        return False
    versions = client.search_model_versions(f"name='{MODEL_NAME}'")
    cand_v = next((v for v in versions if v.run_id == candidate_run_id), None)
    if cand_v is None:
        logger.error("no model version for candidate run")
        return False
    for v in prod:
        client.transition_model_version_stage(MODEL_NAME, v.version, "Archived")
    client.transition_model_version_stage(MODEL_NAME, cand_v.version, "Production")
    logger.info(f"promoted version {cand_v.version} to Production")
    return True