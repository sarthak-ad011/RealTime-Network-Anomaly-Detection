"""Lightweight data validation. Run before every training job — fail fast."""
from __future__ import annotations

from typing import List

import pandas as pd
from loguru import logger


def _expect_not_empty(df):
    return (not df.empty), f"{len(df)} rows"


def _expect_columns(df, required):
    missing = set(required) - set(df.columns)
    return (not missing, f"missing: {sorted(missing)}" if missing else "all present")


def _expect_nonneg(df, cols):
    for c in cols:
        if c in df.columns and (df[c] < 0).any():
            return False, f"{c} has negatives"
    return True, "all non-negative"


def _expect_label_dist(df, min_ratio=0.001):
    if "label_binary" not in df.columns:
        return False, "label_binary missing"
    ratio = df["label_binary"].mean()
    return (ratio >= min_ratio, f"attack ratio {ratio:.4f}")


def _expect_no_nulls(df, cols):
    present = [c for c in cols if c in df.columns]
    for c in present:
        if df[c].isna().any():
            return False, f"{c} has nulls"
    return True, "no nulls"


def validate(df: pd.DataFrame, feature_cols: List[str]) -> bool:
    """Returns True only if every check passes."""
    checks = [
        ("not empty", _expect_not_empty(df)),
        ("columns", _expect_columns(df, list(feature_cols) + ["label_binary"])),
        ("non-negative", _expect_nonneg(df, ["Flow Duration"])),
        ("label distribution", _expect_label_dist(df)),
        ("no nulls", _expect_no_nulls(df, feature_cols)),
    ]
    ok = True
    for name, (passed, msg) in checks:
        logger.info(f"{'OK  ' if passed else 'FAIL'} {name}: {msg}")
        ok = ok and passed
    return ok
