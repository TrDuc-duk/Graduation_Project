"""Baseline chỉ dùng thông tin đã biết tại t; đánh giá trên đúng tập mẫu của model."""
import numpy as np
import pandas as pd


def persistence(samples: pd.DataFrame) -> np.ndarray:
    return samples["AQI"].to_numpy(dtype=float)


def trailing_mean_24h(samples: pd.DataFrame) -> np.ndarray:
    return samples["AQI_roll24_mean"].to_numpy(dtype=float)


def same_hour_of_day(samples: pd.DataFrame, aqi_grid: np.ndarray, h: int, max_days: int = 7) -> np.ndarray:
    """Giá trị gần nhất có timestamp ≤ t và cùng giờ trong ngày với t+h.

    samples.index là vị trí trên lưới giờ liên tục; aqi_grid là AQI đầu vào theo lưới.
    Không dùng t+h-24h trực tiếp (với h>24 đó vẫn là tương lai)."""
    pos = samples.index.to_numpy()
    t_hour = samples["time"].dt.hour.to_numpy()
    target_hour = (t_hour + h) % 24
    k0 = (t_hour - target_hour) % 24
    pred = np.full(len(samples), np.nan)
    for d in range(max_days):
        idx = pos - k0 - 24 * d
        ok = np.isnan(pred) & (idx >= 0)
        cand = np.full(len(samples), np.nan)
        cand[ok] = aqi_grid[idx[ok]]
        pred = np.where(np.isnan(pred), cand, pred)
    return pred


def evaluate_baselines(samples: pd.DataFrame, aqi_grid: np.ndarray, h: int) -> dict[str, np.ndarray]:
    return {
        "persistence": persistence(samples),
        "mean_24h": trailing_mean_24h(samples),
        "same_hour_of_day": same_hour_of_day(samples, aqi_grid, h),
    }
