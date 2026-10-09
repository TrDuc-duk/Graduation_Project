"""Chia train/val/test theo thời gian. Một mẫu (t, t+h) thuộc tập S chỉ khi cả t và t+h thuộc S."""
import numpy as np
import pandas as pd

from src import config
from src.targets import target_column

SEGMENTS = ("train", "val", "test")

DEFAULT_BOUNDS = {
    "train_start": config.TRAIN_START,
    "train_end": config.TRAIN_END,
    "val_end": config.VAL_END,
    "test_end": config.TEST_END,
}


def label_segment(times: pd.Series, bounds: dict | None = None) -> pd.Series:
    """Nhãn 'train'/'val'/'test' theo đoạn nửa kín [start, end); ngoài đoạn -> None."""
    b = bounds or DEFAULT_BOUNDS
    t = pd.Series(times).reset_index(drop=True)
    out = pd.Series([None] * len(t), dtype=object)
    out[(t >= b["train_start"]) & (t < b["train_end"])] = "train"
    out[(t >= b["train_end"]) & (t < b["val_end"])] = "val"
    out[(t >= b["val_end"]) & (t < b["test_end"])] = "test"
    out.index = pd.Series(times).index
    return out


def bounds_from_ratios(grid_times: pd.Series, ratios=(0.70, 0.85)) -> dict:
    """Mốc cắt theo floor(N * tỷ_lệ_tích_lũy) trên lưới giờ đầy đủ."""
    t = pd.Series(grid_times).reset_index(drop=True)
    n = len(t)
    return {
        "train_start": t.iloc[0],
        "train_end": t.iloc[int(np.floor(n * ratios[0]))],
        "val_end": t.iloc[int(np.floor(n * ratios[1]))],
        "test_end": t.iloc[-1] + pd.Timedelta(hours=1),
    }


def legacy_only_bounds(grid_times: pd.Series) -> dict:
    """Split 70/15/15 riêng trong đoạn nguồn cũ (trước SOURCE_SWITCH)."""
    t = pd.Series(grid_times)
    legacy = t[t < config.SOURCE_SWITCH]
    b = bounds_from_ratios(legacy)
    b["test_end"] = config.SOURCE_SWITCH
    return b


def source_of(times: pd.Series) -> pd.Series:
    return pd.Series(np.where(pd.Series(times) < config.SOURCE_SWITCH, "legacy", "open_meteo"),
                     index=pd.Series(times).index)


def select_valid_samples(data: pd.DataFrame, h: int, segment: str, feature_cols: list[str],
                         bounds: dict | None = None,
                         require_complete_features: bool = True) -> tuple[pd.DataFrame, dict]:
    """data: features + `time` + target_AQI_h{h}, RangeIndex theo lưới giờ.

    Trả về (mẫu hợp lệ giữ nguyên index lưới, log số mẫu bị loại theo nguyên nhân)."""
    if segment not in SEGMENTS:
        raise ValueError(segment)
    tcol = target_column(h)
    seg_t = label_segment(data["time"], bounds)
    seg_target = label_segment(data["time"] + pd.Timedelta(hours=h), bounds)
    in_seg = seg_t == segment
    crosses = in_seg & (seg_target != segment)
    cand = in_seg & ~crosses
    target_missing = cand & data[tcol].isna()
    cand2 = cand & ~target_missing
    feat_nan = data[feature_cols].isna()
    # require_complete_features=False: giữ hàng thiếu feature để XGBoost xử lý NaN native
    feature_missing = cand2 & feat_nan.any(axis=1) if require_complete_features else cand2 & False
    keep = cand2 & ~feature_missing
    log = {
        "segment": segment, "horizon": h,
        "rows_with_t_in_segment": int(in_seg.sum()),
        "dropped_label_outside_segment": int(crosses.sum()),
        "dropped_missing_target": int(target_missing.sum()),
        "dropped_missing_feature": int(feature_missing.sum()),
        "kept": int(keep.sum()),
        "missing_feature_by_column": {c: int(n) for c, n in
                                      feat_nan[feature_missing].sum().items() if n > 0},
    }
    return data.loc[keep], log


def count_samples_by_source(samples: pd.DataFrame) -> dict:
    counts = source_of(samples["time"]).value_counts()
    return {"legacy": int(counts.get("legacy", 0)), "open_meteo": int(counts.get("open_meteo", 0))}
