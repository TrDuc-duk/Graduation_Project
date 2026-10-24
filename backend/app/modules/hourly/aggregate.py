"""Tổng hợp số đo thô thành dữ liệu giờ (backend_design 7). Thuần Python, không đụng DB nên dễ unit test.

Nhãn giờ `h` = cửa sổ (h − 1 giờ, h] theo `measured_at`. AQI giờ = `compute_aqi` của PM trung bình giờ,
cùng hàm với phần ML (P4), không viết lại công thức.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import fmean

from src.aqi import aqi_pm10, aqi_pm25, compute_aqi

from app.core.timeutil import floor_hour
from app.modules.telemetry.qc import EXCLUDE_MASK, QcFlag

HOUR = timedelta(hours=1)
SECONDS_PER_HOUR = 3600


@dataclass(frozen=True)
class Sample:
    """Một số đo thô đã được chọn cho tổng hợp (bản SUPERSEDED đã bị bỏ ở truy vấn).

    `excluded` = mẫu không được dùng (qua Gateway chưa duyệt hoặc batch nghi cũ): chỉ đếm vào `n_excluded`.
    """

    measured_at: datetime
    received_at: datetime
    max_age_s: int | None
    qc_flags: int
    excluded: bool
    pm25: float | None = None
    pm10: float | None = None
    temperature: float | None = None
    humidity: float | None = None
    co2: float | None = None
    tvoc: float | None = None


@dataclass(frozen=True)
class HourAggregate:
    """Kết quả một giờ, đúng các cột tính được của `node_hourly`."""

    hour_end: datetime
    n_samples: int
    n_excluded: int
    n_time_estimated: int
    n_time_ambiguous: int
    expected_samples: float | None
    coverage: float | None
    n_pm25: int
    n_pm10: int
    n_temperature: int
    n_humidity: int
    n_co2: int
    pm25_avg: float | None
    pm10_avg: float | None
    temperature_avg: float | None
    humidity_avg: float | None
    co2_avg: float | None
    tvoc_avg: float | None
    pm25_max: float | None
    pm10_max: float | None
    aqi: int | None
    aqi_pm25: int | None
    aqi_pm10: int | None
    qc_flags: int


def hour_label(t: datetime) -> datetime:
    """Nhãn giờ chứa thời điểm t: 13:00:01–14:00:00 → 14:00 (mẫu đúng 14:00:00 thuộc giờ 14:00)."""
    start = floor_hour(t)
    return start if t == start else start + HOUR


def expected_samples(interval_s: int | None) -> float | None:
    """Số mẫu kỳ vọng trong một giờ = 3600 / chu kỳ, không làm tròn (R27); chưa biết chu kỳ → None."""
    return SECONDS_PER_HOUR / interval_s if interval_s else None


def aggregate_hour(
    hour_end: datetime, samples: list[Sample], interval_s: int | None, min_samples: int
) -> HourAggregate | None:
    """Tổng hợp các mẫu của một giờ; giờ không có mẫu nào (kể cả mẫu bị loại) → None (không có dòng).

    Một biến chỉ có giá trị trung bình khi có ít nhất `min_samples` mẫu khác null (P1).
    """
    if not samples:
        return None
    used = [s for s in samples if not s.excluded]

    def values(attr: str) -> list[float]:
        return [v for s in used if (v := getattr(s, attr)) is not None]

    def mean(vals: list[float]) -> float | None:
        return fmean(vals) if len(vals) >= min_samples and vals else None

    pm25, pm10 = values("pm25"), values("pm10")
    pm25_avg, pm10_avg = mean(pm25), mean(pm10)
    expected = expected_samples(interval_s)
    flags = 0
    for s in used:
        flags |= s.qc_flags
    return HourAggregate(
        hour_end=hour_end,
        n_samples=len(used),
        n_excluded=len(samples) - len(used),
        n_time_estimated=sum(1 for s in used if s.qc_flags & QcFlag.TIME_ESTIMATED),
        n_time_ambiguous=sum(1 for s in used if _is_time_ambiguous(s)),
        expected_samples=expected,
        coverage=min(1.0, len(used) / expected) if expected else None,
        n_pm25=len(pm25),
        n_pm10=len(pm10),
        n_temperature=len(values("temperature")),
        n_humidity=len(values("humidity")),
        n_co2=len(values("co2")),
        pm25_avg=pm25_avg,
        pm10_avg=pm10_avg,
        temperature_avg=mean(values("temperature")),
        humidity_avg=mean(values("humidity")),
        co2_avg=mean(values("co2")),
        tvoc_avg=mean(values("tvoc")),
        pm25_max=max(pm25) if pm25_avg is not None else None,
        pm10_max=max(pm10) if pm10_avg is not None else None,
        aqi=aqi_from_pm(pm25_avg, pm10_avg),
        aqi_pm25=_as_int(aqi_pm25(pm25_avg)) if pm25_avg is not None else None,
        aqi_pm10=_as_int(aqi_pm10(pm10_avg)) if pm10_avg is not None else None,
        qc_flags=flags & ~EXCLUDE_MASK,  # mẫu được dùng thì không mang cờ loại (kể cả khi tính as-of)
    )


def aggregate(samples: list[Sample], interval_s: int | None, min_samples: int) -> dict[datetime, HourAggregate]:
    """Chia mẫu theo nhãn giờ rồi tổng hợp từng giờ; trả {hour_end: kết quả} (giờ trống không có khóa)."""
    by_hour: dict[datetime, list[Sample]] = {}
    for s in samples:
        by_hour.setdefault(hour_label(s.measured_at), []).append(s)
    out = {}
    for hour_end, group in sorted(by_hour.items()):
        result = aggregate_hour(hour_end, group, interval_s, min_samples)
        if result is not None:
            out[hour_end] = result
    return out


def aqi_from_pm(pm25: float | None, pm10: float | None) -> int | None:
    """AQI = compute_aqi(PM2.5, PM10) của giá trị trung bình; thiếu một trong hai hoặc ngoài bảng → None."""
    if pm25 is None or pm10 is None:
        return None
    return _as_int(compute_aqi(pm25, pm10))


def _is_time_ambiguous(s: Sample) -> bool:
    """Mẫu có khoảng thời điểm đo thật [received_at − max_age_s, received_at] vắt qua ranh giới giờ (R6)."""
    if s.max_age_s is None:
        return False
    return hour_label(s.received_at - timedelta(seconds=s.max_age_s)) != hour_label(s.received_at)


def _as_int(value: float) -> int | None:
    """AQI dạng số nguyên; NaN (ngoài bảng) → None."""
    return None if math.isnan(value) else int(value)
