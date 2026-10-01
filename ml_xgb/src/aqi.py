"""Tính AQI theo Bảng 3.3 / 3.4 của báo cáo, từ PM từng dòng (không trung bình 24h)."""
import numpy as np
import pandas as pd

# (BP_lo, BP_hi, I_lo, I_hi)
PM25_BREAKPOINTS = [
    (0.0, 12.0, 0, 50),
    (12.1, 35.4, 51, 100),
    (35.5, 55.4, 101, 150),
    (55.5, 150.4, 151, 200),
    (150.5, 250.4, 201, 300),
    (250.5, 500.4, 301, 500),
]
PM10_BREAKPOINTS = [
    (0, 54, 0, 50),
    (55, 154, 51, 100),
    (155, 254, 101, 150),
    (255, 354, 151, 200),
    (355, 424, 201, 300),
    (425, 604, 301, 500),
]
AQI_MAX = 500


def _truncate(c: np.ndarray, decimals: int) -> np.ndarray:
    # +1e-9 chống sai số nhị phân (vd 12.1 * 10 = 120.99999...)
    scale = 10**decimals
    return np.floor(c * scale + 1e-9) / scale


def _round_half_up(x: np.ndarray) -> np.ndarray:
    return np.floor(x + 0.5 + 1e-9)


def _sub_index(c: np.ndarray, breakpoints) -> np.ndarray:
    out = np.full(c.shape, np.nan)
    valid = ~np.isnan(c)
    for bp_lo, bp_hi, i_lo, i_hi in breakpoints:
        m = valid & (c >= bp_lo) & (c <= bp_hi)
        out[m] = (i_hi - i_lo) / (bp_hi - bp_lo) * (c[m] - bp_lo) + i_lo
    out = _round_half_up(out)
    # Nồng độ vượt bảng -> AQI 500 (theo Bảng 4.11 báo cáo)
    out[valid & (c > breakpoints[-1][1])] = AQI_MAX
    # Khoảng hở giữa các breakpoint (không xảy ra sau khi cắt chữ số) -> NaN
    return out


def _sub_index_any(x, decimals: int, breakpoints):
    arr = np.asarray(x, dtype=float)
    out = _sub_index(_truncate(np.atleast_1d(arr), decimals), breakpoints)
    return out.reshape(arr.shape) if arr.ndim else out[0]


def aqi_pm25(pm25):
    return _sub_index_any(pm25, 1, PM25_BREAKPOINTS)


def aqi_pm10(pm10):
    return _sub_index_any(pm10, 0, PM10_BREAKPOINTS)


def compute_aqi(pm25, pm10):
    """AQI = max(I_PM2.5, I_PM10). Nhận scalar/array/Series; NaN lan truyền thành NaN."""
    a = aqi_pm25(pm25)
    b = aqi_pm10(pm10)
    res = np.where(np.isnan(a) | np.isnan(b), np.nan, np.fmax(a, b))
    if isinstance(pm25, pd.Series):
        return pd.Series(res, index=pm25.index, name="AQI")
    return float(res) if res.ndim == 0 else res
