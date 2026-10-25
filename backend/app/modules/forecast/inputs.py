"""Đầu vào dự báo (backend_design 8.4): dòng giờ → bảng `history` đúng schema ML; độ sẵn sàng khi thiếu lịch sử.

Thuần Python, không đụng DB (dữ liệu đã được chụp trong transaction trước khi chạy model trong thread).
"""

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import pandas as pd

from app.core.timeutil import LOCAL_TZ

HOUR = timedelta(hours=1)
FFILL_LIMIT_HOURS = 3  # chính sách ffill3h lấp khoảng trống ≤ 3 giờ, giống lúc train
ML_COLUMNS = ("AQI", "pm10", "pm2_5", "Humidity", "Temperature")


@dataclass(frozen=True)
class HourRow:
    """Một giờ đầu vào: nhãn h (UTC), 5 biến ML, revision (null khi tính as-of), số mẫu, độ phủ."""

    hour_end: datetime
    aqi: float | None
    pm25: float | None
    pm10: float | None
    temperature: float | None
    humidity: float | None
    revision: int | None = None
    n_samples: int | None = None
    coverage: float | None = None

    def complete(self) -> bool:
        """Đủ cả 5 biến (với `no_fill`, thiếu một biến là thiếu giờ)."""
        return None not in (self.aqi, self.pm25, self.pm10, self.temperature, self.humidity)


def local_naive(t: datetime) -> pd.Timestamp:
    """UTC → giờ Việt Nam bỏ múi giờ (yêu cầu M2 của ML)."""
    return pd.Timestamp(t.astimezone(LOCAL_TZ).replace(tzinfo=None))


def history_frame(rows: list[HourRow], t: datetime) -> pd.DataFrame:
    """Bảng `history` cho `build_inference_features`: time + AQI, pm10, pm2_5, Humidity, Temperature.

    Đổi tên `AQI ← aqi`, `pm2_5 ← pm25_avg`, …; giờ `t` không có dòng nào thì thêm dòng NaN (P3) để `nan_policy`
    của model quyết định.
    """
    records = [
        {"time": local_naive(r.hour_end), "AQI": _f(r.aqi), "pm10": _f(r.pm10), "pm2_5": _f(r.pm25),
         "Humidity": _f(r.humidity), "Temperature": _f(r.temperature)}
        for r in rows
        if r.hour_end <= t
    ]  # fmt: skip
    if not any(r.hour_end == t for r in rows):
        records.append({"time": local_naive(t), **dict.fromkeys(ML_COLUMNS, math.nan)})
    frame = pd.DataFrame(records, columns=["time", *ML_COLUMNS]).sort_values("time", ignore_index=True)
    frame["time"] = frame["time"].astype("datetime64[us]")
    return frame


def history_records(rows: list[HourRow]) -> list[dict]:
    """Các dòng giờ đã dùng, dạng lưu `forecast_input_history` (R29): giờ Việt Nam, 5 biến ML, revision."""
    return [
        {"time": local_naive(r.hour_end).isoformat(), "AQI": r.aqi, "pm10": r.pm10, "pm2_5": r.pm25,
         "Humidity": r.humidity, "Temperature": r.temperature, "revision": r.revision}
        for r in sorted(rows, key=lambda r: r.hour_end)
    ]  # fmt: skip


def sha256_json(value: object) -> str:
    """SHA-256 của JSON chuẩn hóa (khóa sắp xếp) — để đối chiếu đầu vào khi tái hiện."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def readiness(rows: list[HourRow], t: datetime, required_hours: int, policy: str) -> tuple[int, int]:
    """(missing_hours, eta_hours) trong cửa sổ `required_hours` giờ kết thúc ở t (backend_design 8.4).

    - `no_fill`: giờ thiếu = giờ không có dòng hoặc thiếu một trong 5 biến.
    - `ffill3h`: chỉ tính các đoạn thiếu dài hơn 3 giờ liên tiếp.
    `eta_hours` = số giờ tới khi giờ thiếu gần nhất trượt ra khỏi cửa sổ.
    """
    complete = {r.hour_end for r in rows if r.complete()}
    window = [t - i * HOUR for i in range(required_hours - 1, -1, -1)]  # cũ → mới
    missing = [h for h in window if h not in complete]
    if policy == "ffill3h":
        missing = [h for run in _runs(missing) if len(run) > FFILL_LIMIT_HOURS for h in run]
    if not missing:
        return 0, 0
    newest = max(missing)
    return len(missing), int((newest + required_hours * HOUR - t) / HOUR)


def _runs(hours: list[datetime]) -> list[list[datetime]]:
    """Gom các giờ liên tiếp thành từng đoạn."""
    runs: list[list[datetime]] = []
    for h in hours:
        if runs and h - runs[-1][-1] == HOUR:
            runs[-1].append(h)
        else:
            runs.append([h])
    return runs


def _f(value: float | None) -> float:
    """Giá trị null → NaN (pandas)."""
    return math.nan if value is None else float(value)
