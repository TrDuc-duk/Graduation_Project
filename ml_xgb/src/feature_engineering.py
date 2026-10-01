"""Feature tại thời điểm t, chỉ dùng dữ liệu đã biết (≤ t). Hàm build_feature_matrix
được dùng nguyên văn cho cả train và inference."""
import numpy as np
import pandas as pd

from src import config
from src.aqi import aqi_pm10, aqi_pm25

TIME_FEATURES = ["hour", "dayofweek", "month", "hour_sin", "hour_cos",
                 "dayofweek_sin", "dayofweek_cos", "month_sin", "month_cos"]
FUTURE_TIME_FEATURES = ["hour", "dayofweek", "month", "hour_sin", "hour_cos"]
# Feature bổ sung (tùy chọn): tất cả chỉ dùng dữ liệu ≤ t
EXTRA_FEATURES = ["pm_ratio", "aqi_sub_pm25", "aqi_sub_pm10", "aqi_sub_gap", "AQI_ewm6", "AQI_ewm24",
                  "AQI_over_roll24_mean", "doy_sin", "doy_cos"]


def _time_block(times: pd.Series, suffix: str = "") -> dict[str, pd.Series]:
    hour = times.dt.hour
    dow = times.dt.dayofweek
    month = times.dt.month
    cols = {
        "hour": hour, "dayofweek": dow, "month": month,
        "hour_sin": np.sin(2 * np.pi * hour / 24), "hour_cos": np.cos(2 * np.pi * hour / 24),
        "dayofweek_sin": np.sin(2 * np.pi * dow / 7), "dayofweek_cos": np.cos(2 * np.pi * dow / 7),
        "month_sin": np.sin(2 * np.pi * (month - 1) / 12), "month_cos": np.cos(2 * np.pi * (month - 1) / 12),
    }
    names = FUTURE_TIME_FEATURES if suffix else TIME_FEATURES
    return {f"{n}{suffix}": cols[n] for n in names}


def _extra_block(grid: pd.DataFrame, base: dict[str, pd.Series]) -> dict[str, pd.Series]:
    pm25, pm10, aqi = grid["pm2_5"], grid["pm10"], grid["AQI"]
    sub25 = pd.Series(aqi_pm25(pm25.to_numpy()), index=grid.index)
    sub10 = pd.Series(aqi_pm10(pm10.to_numpy()), index=grid.index)

    def ewm(span: int) -> pd.Series:  # chỉ hợp lệ khi cả cửa sổ `span` giờ gần nhất đều có dữ liệu
        full = aqi.isna().rolling(span, min_periods=span).sum() == 0
        return aqi.ewm(span=span, adjust=False).mean().where(full)

    doy = grid["time"].dt.dayofyear
    return {
        "pm_ratio": (pm25 / pm10.where(pm10 > 0)),
        "aqi_sub_pm25": sub25, "aqi_sub_pm10": sub10, "aqi_sub_gap": sub25 - sub10,
        "AQI_ewm6": ewm(6), "AQI_ewm24": ewm(24),
        "AQI_over_roll24_mean": aqi / base["AQI_roll24_mean"].where(base["AQI_roll24_mean"] > 0),
        "doy_sin": np.sin(2 * np.pi * doy / 366), "doy_cos": np.cos(2 * np.pi * doy / 366),
    }


def get_feature_columns(policy: str = config.NAN_POLICY, include_future_time: bool = False,
                        h: int | None = None, include_extra: bool = False) -> list[str]:
    """Danh sách cột tường minh, có thứ tự; không bao giờ suy ra từ df.columns."""
    cols = list(config.BASE_COLUMNS)
    cols += [f"{c}_lag{k}" for c in config.BASE_COLUMNS for k in config.LAG_HOURS]
    cols += [f"{c}_roll{w}_{s}" for c in config.BASE_COLUMNS
             for w in config.ROLLING_WINDOWS for s in config.ROLLING_STATS]
    cols += [f"{c}_diff{k}" for c in config.BASE_COLUMNS for k in config.LAG_HOURS]
    cols += TIME_FEATURES
    if policy == "ffill3h":
        cols += [f"{c}_is_filled" for c in config.BASE_COLUMNS]
        cols += [f"{c}_age_hours" for c in config.BASE_COLUMNS]
    if include_extra:
        cols += EXTRA_FEATURES
    if include_future_time:
        if h is None:
            raise ValueError("include_future_time cần h")
        cols += [f"{n}_h{h}" for n in FUTURE_TIME_FEATURES]
    return cols


def build_feature_matrix(grid: pd.DataFrame, policy: str = config.NAN_POLICY,
                         include_future_time: bool = False, h: int | None = None,
                         include_extra: bool = False) -> pd.DataFrame:
    """grid: lưới giờ liên tục (đã qua apply_nan_policy). Trả về DataFrame có cột `time` + features."""
    if not (grid["time"].diff().dropna() == pd.Timedelta(hours=1)).all():
        raise ValueError("Lưới thời gian phải liên tục theo giờ")
    cols: dict[str, pd.Series] = {"time": grid["time"]}
    for c in config.BASE_COLUMNS:
        s = grid[c]
        cols[c] = s
        for k in config.LAG_HOURS:
            cols[f"{c}_lag{k}"] = s.shift(k)
            cols[f"{c}_diff{k}"] = s - s.shift(k)
        for w in config.ROLLING_WINDOWS:
            r = s.rolling(window=w, min_periods=w)  # cửa sổ kết thúc tại t
            for stat in config.ROLLING_STATS:
                cols[f"{c}_roll{w}_{stat}"] = getattr(r, stat)()
    cols.update(_time_block(grid["time"]))
    if policy == "ffill3h":
        for c in config.BASE_COLUMNS:
            cols[f"{c}_is_filled"] = grid[f"{c}_is_filled"]
            cols[f"{c}_age_hours"] = grid[f"{c}_age_hours"]
    if include_extra:
        cols.update(_extra_block(grid, cols))
    if include_future_time:
        cols.update(_time_block(grid["time"] + pd.Timedelta(hours=h), suffix=f"_h{h}"))
    out = pd.DataFrame(cols)
    return out[["time"] + get_feature_columns(policy, include_future_time, h, include_extra)]
