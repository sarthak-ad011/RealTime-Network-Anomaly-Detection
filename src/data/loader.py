"""Data loading + preprocessing for CIC-IDS2017."""
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from loguru import logger

FEATURE_COLS = [
    "Flow Duration", "Total Fwd Packets", "Total Backward Packets",
    "Fwd Packet Length Mean", "Bwd Packet Length Mean",
    "Flow Bytes/s", "Flow Packets/s",
    "Flow IAT Mean", "Fwd IAT Mean", "Bwd IAT Mean",
    "Packet Length Mean", "Packet Length Std",
    "SYN Flag Count", "ACK Flag Count", "Average Packet Size",
]
LABEL_COL = "Label"


@dataclass
class DataBundle:
    X_train: np.ndarray
    X_val: np.ndarray
    X_test: np.ndarray
    y_train: np.ndarray
    y_val: np.ndarray
    y_test: np.ndarray
    scaler: StandardScaler
    feature_names: list


def load_raw(data_dir: Path) -> pd.DataFrame:
    csvs = sorted(Path(data_dir).glob("*.csv"))
    if not csvs:
        raise FileNotFoundError(f"No CSVs in {data_dir}")
    logger.info(f"Loading {len(csvs)} CSVs")
    df = pd.concat([pd.read_csv(f, low_memory=False) for f in csvs], ignore_index=True)
    df.columns = df.columns.str.strip()    # CIC has leading spaces!
    return df


def clean(df: pd.DataFrame) -> pd.DataFrame:
    df = df.replace([np.inf, -np.inf], np.nan)
    before = len(df)
    df = df.dropna(subset=FEATURE_COLS + [LABEL_COL])
    logger.info(f"Dropped {before - len(df)} rows with NaN/inf")
    df["label_binary"] = (df[LABEL_COL].str.strip() != "BENIGN").astype(int)
    return df


def prepare(df, test_size=0.2, val_size=0.1, seed=42, benign_only_train=True):
    X = df[FEATURE_COLS].values.astype(np.float32)
    y = df["label_binary"].values.astype(np.int64)
    X_trainval, X_test, y_trainval, y_test = train_test_split(
        X, y, test_size=test_size, stratify=y, random_state=seed)
    X_train, X_val, y_train, y_val = train_test_split(
        X_trainval, y_trainval, test_size=val_size / (1 - test_size),
        stratify=y_trainval, random_state=seed)
    if benign_only_train:
        mask = y_train == 0
        X_train, y_train = X_train[mask], y_train[mask]
    scaler = StandardScaler().fit(X_train)
    return DataBundle(
        X_train=scaler.transform(X_train), X_val=scaler.transform(X_val),
        X_test=scaler.transform(X_test), y_train=y_train, y_val=y_val,
        y_test=y_test, scaler=scaler, feature_names=FEATURE_COLS)
