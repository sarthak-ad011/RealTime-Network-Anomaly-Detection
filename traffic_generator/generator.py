"""Synthetic traffic generator for the demo. Modes: normal, attack, drift."""
import argparse
import asyncio
import random
import time

import httpx
import numpy as np

BENIGN_MEAN = np.array([1.5e6, 12, 10, 250, 200, 5e3, 50, 1e5, 5e4, 5e4, 220, 180, 0.1, 5, 230], dtype=np.float32)
BENIGN_STD = np.array([5e5, 5, 4, 80, 70, 2e3, 20, 4e4, 2e4, 2e4, 70, 60, 0.3, 2, 75], dtype=np.float32)


def sample_normal():
    return (BENIGN_MEAN + BENIGN_STD * np.random.randn(15)).tolist()


def sample_ddos():
    v = sample_normal()
    v[0], v[1], v[5], v[12] = 100, 5000, 5e5, 50
    return v


def sample_drifted(strength):
    drift = np.array([0.5, 0.3, 0.2, 0.4, 0.3, 0.6, 0.2, 0.5, 0.3, 0.3, 0.4, 0.5, 0, 0.2, 0.4])
    return (BENIGN_MEAN * (1 + strength * drift) + BENIGN_STD * np.random.randn(15)).tolist()


async def run(args):
    url = f"{args.endpoint}/predict"
    sent = 0
    start = time.time()
    async with httpx.AsyncClient() as client:
        while True:
            if args.mode == "normal":
                features = sample_normal()
            elif args.mode == "attack":
                features = sample_ddos() if random.random() < 0.05 else sample_normal()
            elif args.mode == "drift":
                strength = min(1.0, (time.time() - start) / 60 / args.drift_minutes)
                features = sample_drifted(strength)
            else:
                raise ValueError(args.mode)
            try:
                r = await client.post(url, json={"features": features}, timeout=5.0)
                sent += 1
                if sent % 50 == 0:
                    print(f"sent={sent} status={r.status_code}")
            except Exception as e:
                print(f"err: {e}")
            await asyncio.sleep(1.0 / args.rps)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--endpoint", required=True)
    p.add_argument("--mode", choices=["normal", "attack", "drift"], default="normal")
    p.add_argument("--rps", type=float, default=10.0)
    p.add_argument("--drift-minutes", type=float, default=10.0)
    asyncio.run(run(p.parse_args()))