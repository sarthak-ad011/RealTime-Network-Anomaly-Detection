from dataclasses import dataclass, asdict
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, TensorDataset
from sklearn.metrics import average_precision_score, roc_auc_score, precision_recall_fscore_support
from loguru import logger


@dataclass
class LSTMConfig:
    seq_len: int = 15
    input_dim: int = 1
    hidden_dim: int = 32
    latent_dim: int = 8
    num_layers: int = 1
    lr: float = 1e-3
    batch_size: int = 256
    epochs: int = 20
    device: str = "cuda" if torch.cuda.is_available() else "cpu"


class LSTMAutoencoder(nn.Module):
    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.encoder = nn.LSTM(cfg.input_dim, cfg.hidden_dim, cfg.num_layers, batch_first=True)
        self.to_latent = nn.Linear(cfg.hidden_dim, cfg.latent_dim)
        self.from_latent = nn.Linear(cfg.latent_dim, cfg.hidden_dim)
        self.decoder = nn.LSTM(cfg.hidden_dim, cfg.hidden_dim, cfg.num_layers, batch_first=True)
        self.output = nn.Linear(cfg.hidden_dim, cfg.input_dim)

    def forward(self, x):
        _, (h, _) = self.encoder(x)
        z = self.to_latent(h[-1])
        h_dec = self.from_latent(z).unsqueeze(0)
        decoder_input = h_dec.permute(1, 0, 2).repeat(1, self.cfg.seq_len, 1)
        decoded, _ = self.decoder(decoder_input)
        return self.output(decoded)


class LSTMDetector:
    def __init__(self, cfg):
        self.cfg = cfg
        self.model = LSTMAutoencoder(cfg).to(cfg.device)
        self.threshold = None

    @staticmethod
    def _to_seq(X):
        return torch.tensor(X, dtype=torch.float32).unsqueeze(-1)

    def fit(self, X_train, X_val):
        ds = TensorDataset(self._to_seq(X_train))
        loader = DataLoader(ds, batch_size=self.cfg.batch_size, shuffle=True)
        opt = optim.Adam(self.model.parameters(), lr=self.cfg.lr)
        loss_fn = nn.MSELoss()
        for epoch in range(self.cfg.epochs):
            self.model.train()
            total = 0.0
            for (batch,) in loader:
                batch = batch.to(self.cfg.device)
                opt.zero_grad()
                loss = loss_fn(self.model(batch), batch)
                loss.backward(); opt.step()
                total += loss.item() * batch.size(0)
            logger.info(f"epoch {epoch+1}/{self.cfg.epochs} loss={total/len(ds):.5f}")
        val_scores = self.score(X_val)
        self.threshold = float(np.percentile(val_scores, 95))
        return self

    @torch.no_grad()
    def score(self, X):
        self.model.eval()
        x = self._to_seq(X).to(self.cfg.device)
        recon = self.model(x)
        return ((recon - x) ** 2).mean(dim=(1, 2)).cpu().numpy()

    def predict(self, X, threshold=None):
        thr = threshold if threshold is not None else self.threshold
        return (self.score(X) > thr).astype(int)

    def evaluate(self, X, y):
        scores, preds = self.score(X), self.predict(X)
        p, r, f1, _ = precision_recall_fscore_support(y, preds, average="binary", zero_division=0)
        return {"auc_roc": float(roc_auc_score(y, scores)),
                "auc_pr": float(average_precision_score(y, scores)),
                "precision": float(p), "recall": float(r), "f1": float(f1),
                "threshold": self.threshold}

    def state_dict(self):
        return {"model": self.model.state_dict(), "cfg": asdict(self.cfg), "threshold": self.threshold}