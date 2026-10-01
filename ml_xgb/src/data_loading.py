"""Đọc dataset.csv. File có 2 định dạng timestamp (có/không giây) nên dùng ISO8601."""
import hashlib
from pathlib import Path

import pandas as pd

from src import config

EXPECTED_COLUMNS = ["time", "AQI", "pm10", "pm2_5", "Humidity", "Temperature"]


def assert_schema(df: pd.DataFrame) -> None:
    if list(df.columns) != EXPECTED_COLUMNS:
        raise ValueError(f"Cột không khớp: {list(df.columns)} != {EXPECTED_COLUMNS}")
    if df["time"].isna().any():
        raise ValueError("Có timestamp không parse được (NaT)")
    if df["time"].dt.tz is not None:
        raise ValueError("Timestamp phải là giờ địa phương naive (không offset)")


def load_raw_dataset(path: Path = config.DATA_PATH) -> pd.DataFrame:
    df = pd.read_csv(path)
    if list(df.columns) != EXPECTED_COLUMNS:
        raise ValueError(f"Cột không khớp: {list(df.columns)} != {EXPECTED_COLUMNS}")
    df["time"] = pd.to_datetime(df["time"], format="ISO8601")
    for col in config.BASE_COLUMNS:
        df[col] = df[col].astype(float)
    assert_schema(df)
    return df


def compute_file_sha256(path: Path = config.DATA_PATH) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_dataset_hash(path: Path = config.DATA_PATH) -> str:
    digest = compute_file_sha256(path)
    if digest != config.EXPECTED_DATASET_SHA256:
        raise ValueError(
            f"SHA-256 dataset thay đổi: {digest} != {config.EXPECTED_DATASET_SHA256}. "
            "Nếu cố ý cập nhật dữ liệu, cập nhật EXPECTED_DATASET_SHA256 và train lại."
        )
    return digest
