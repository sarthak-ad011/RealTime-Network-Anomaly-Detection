from dataclasses import dataclass

from sklearn.ensemble import IsolationForest
from sklearn.metrics import average_precision_score, precision_recall_fscore_support, roc_auc_score


@dataclass
class IFConfig:
    n_estimators: int = 200
    contamination: float = 0.01
    random_state: int = 42


class IsolationForestDetector:
    def __init__(self, cfg: IFConfig):
        self.cfg = cfg
        self.model = IsolationForest(
            n_estimators=cfg.n_estimators, contamination=cfg.contamination,
            random_state=cfg.random_state, n_jobs=-1)

    def fit(self, X):
        self.model.fit(X)
        return self

    def score(self, X):
        return -self.model.decision_function(X)

    def predict(self, X):
        return (self.model.predict(X) == -1).astype(int)

    def evaluate(self, X, y):
        # score once; sklearn flags an outlier exactly where decision_function < 0,
        # which is score > 0 under our sign flip. Avoids a second full tree traversal.
        scores = self.score(X)
        preds = (scores > 0).astype(int)
        p, r, f1, _ = precision_recall_fscore_support(y, preds, average="binary", zero_division=0)
        return {"auc_roc": float(roc_auc_score(y, scores)),
                "auc_pr": float(average_precision_score(y, scores)),
                "precision": float(p), "recall": float(r), "f1": float(f1)}