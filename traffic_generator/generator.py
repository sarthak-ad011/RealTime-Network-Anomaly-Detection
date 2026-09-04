"""Synthetic traffic generator for the demo. Modes: normal, attack, drift.

Normal traffic is *replayed from the real benign training distribution* rather than
invented constants. Hand-written feature means do not survive contact with the fitted
StandardScaler — every such flow lands far outside the benign manifold and the model
flags 100% of it, which would make the canary's anomaly-flag-rate gate fire on
healthy deploys and make drift detection meaningless.

Usage:
    python traffic_generator/generator.py --endpoint http://localhost:8000 --mode normal --rps 20
    python traffic_generator/generator.py --endpoint http://localhost:8000 --mode drift --drift-minutes 5
"""
import argparse
import asyncio
import random
import time
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

DEFAULT_REFERENCE = Path("data/reference/training_reference.parquet")

# Which feature indices an attack inflates, and by how much. Modelled on the DDoS /
# port-scan flows in CIC-IDS2017: very short duration, huge packet counts and rates,
# elevated SYN flags.
ATTACK_PROFILE = {
    0: ("set", 1.0e2),      # Flow Duration     -> near zero
    1: ("mul", 500.0),      # Total Fwd Packets -> flood
    5: ("mul", 200.0),      # Flow Bytes/s
    6: ("mul", 200.0),      # Flow Packets/s
    12: ("set", 50.0),      # SYN Flag Count
}


def _load_reference(location: str) -> pd.DataFrame:
    """Read the reference dataset from a local path or s3:// URI.

    S3 support lets the generator run as an in-cluster Job, which matters because
    `kubectl port-forward` to a Service pins to a single pod — load driven through
    it never reaches the other replicas.
    """
    if location.startswith("s3://"):
        import io

        import boto3
        bucket, _, key = location[5:].partition("/")
        body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
        return pd.read_parquet(io.BytesIO(body))
    path = Path(location)
    if not path.exists():
        raise SystemExit(
            f"reference dataset not found at {path}\n"
            "It is written by the training pipeline; see scripts/ and the README."
        )
    return pd.read_parquet(path)


class TrafficSource:
    def __init__(self, reference: str):
        df = _load_reference(reference)
        self.rows = df.to_numpy(dtype=np.float64)
        self.cols = df.columns.tolist()
        # per-feature spread, used to shift the distribution in drift mode
        self.std = self.rows.std(axis=0)

    def normal(self):
        return self.rows[random.randrange(len(self.rows))].copy()

    def attack(self):
        v = self.normal()
        for idx, (op, amount) in ATTACK_PROFILE.items():
            v[idx] = amount if op == "set" else v[idx] * amount
        return v

    def drifted(self, strength: float):
        """Shift the benign distribution by `strength` standard deviations.

        This is covariate shift, not an attack: the traffic is still 'normal', it
        simply no longer looks like what the model was trained on. That is exactly
        what the Evidently job should notice.
        """
        v = self.normal()
        return v + strength * 2.5 * self.std


async def run(args):
    src = TrafficSource(args.reference)
    url = f"{args.endpoint.rstrip('/')}/predict"
    sent = anomalies = errors = 0
    start = time.time()
    limits = httpx.Limits(max_connections=50)

    async with httpx.AsyncClient(limits=limits) as client:
        while True:
            if args.duration and (time.time() - start) >= args.duration:
                break

            if args.mode == "normal":
                features = src.normal()
            elif args.mode == "attack":
                features = src.attack() if random.random() < args.attack_rate else src.normal()
            elif args.mode == "drift":
                elapsed_min = (time.time() - start) / 60.0
                strength = min(1.0, elapsed_min / args.drift_minutes)
                features = src.drifted(strength)
            else:
                raise ValueError(args.mode)

            try:
                r = await client.post(url, json={"features": [float(x) for x in features]}, timeout=10.0)
                sent += 1
                if r.status_code == 200 and r.json().get("is_anomaly"):
                    anomalies += 1
            except Exception as exc:
                errors += 1
                if errors <= 3:
                    print(f"error: {exc}")

            if sent and sent % 50 == 0:
                rate = anomalies / sent
                print(f"sent={sent} flagged={anomalies} ({rate:.1%}) errors={errors}")

            await asyncio.sleep(1.0 / args.rps)

    print(f"\ndone: sent={sent} flagged={anomalies} "
          f"({anomalies / sent:.1%} of traffic)" if sent else "done: nothing sent")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--endpoint", required=True)
    p.add_argument("--mode", choices=["normal", "attack", "drift"], default="normal")
    p.add_argument("--rps", type=float, default=10.0)
    p.add_argument("--drift-minutes", type=float, default=10.0)
    p.add_argument("--attack-rate", type=float, default=0.05)
    p.add_argument("--duration", type=float, default=0, help="seconds; 0 = run forever")
    p.add_argument("--reference", default=str(DEFAULT_REFERENCE))
    asyncio.run(run(p.parse_args()))
