"""Lưới giờ liên tục, mask quan sát gốc và chính sách xử lý thiếu.

Lưới có RangeIndex liên tục theo giờ nên shift(k) theo vị trí = dịch đúng k giờ.
Cột AQI_observed không bao giờ bị điền: dùng làm nhãn.
"""
import numpy as np
import pandas as pd

from src import config

NAN_POLICIES = ("no_fill", "ffill3h", "xgb_native_nan")


def sort_and_dedupe(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    df = df.sort_values("time", kind="stable")
    dup = df["time"].duplicated(keep="first")
    return df.loc[~dup].reset_index(drop=True), int(dup.sum())


def build_hourly_grid(df: pd.DataFrame) -> pd.DataFrame:
    """Reindex lên lưới 1h liên tục; giờ thiếu -> NaN, observed=False."""
    df, _ = sort_and_dedupe(df)
    full = pd.date_range(df["time"].min(), df["time"].max(), freq="1h")
    grid = df.set_index("time").reindex(full)
    grid.index.name = "time"
    grid["observed"] = grid.index.isin(df["time"])
    grid = grid.reset_index()
    grid["AQI_observed"] = grid["AQI"]
    return grid


def _age_since_observed(series: pd.Series) -> pd.Series:
    pos = pd.Series(np.arange(len(series)), index=series.index)
    last = pos.where(series.notna()).ffill()
    return pos - last  # NaN nếu chưa từng có quan sát


def _apply_ffill(df: pd.DataFrame, limit: int) -> pd.DataFrame:
    out = df.copy()
    for col in config.BASE_COLUMNS:
        raw = df[col]
        filled = raw.ffill(limit=limit)
        out[col] = filled
        out[f"{col}_is_filled"] = (raw.isna() & filled.notna()).astype(int)
        out[f"{col}_age_hours"] = _age_since_observed(raw)
    return out


def apply_nan_policy(grid: pd.DataFrame, policy: str = config.NAN_POLICY) -> tuple[pd.DataFrame, dict]:
    """Trả về (bảng đặc trưng, metadata policy). AQI_observed luôn giữ nguyên."""
    if policy not in NAN_POLICIES:
        raise ValueError(f"policy không hợp lệ: {policy}")
    if policy == "ffill3h":
        out = _apply_ffill(grid, config.FFILL_LIMIT_HOURS)
        meta = {"name": policy, "ffill_limit_hours": config.FFILL_LIMIT_HOURS,
                "extra_columns": ["{col}_is_filled", "{col}_age_hours"]}
    else:
        out = grid.copy()
        meta = {"name": policy, "xgb_missing": "NaN" if policy == "xgb_native_nan" else None}
    return out, meta


def prepare_grid(df: pd.DataFrame, policy: str = config.NAN_POLICY) -> tuple[pd.DataFrame, dict]:
    """Từ dữ liệu thô -> lưới giờ đã áp chính sách NaN."""
    return apply_nan_policy(build_hourly_grid(df), policy)
