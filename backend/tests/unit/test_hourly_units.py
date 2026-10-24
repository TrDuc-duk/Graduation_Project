"""Unit test tổng hợp giờ (backend_design 7, 18 "Tổng hợp giờ"): không cần DB."""

from datetime import UTC, datetime, timedelta

import pytest
from src.aqi import compute_aqi

from app.modules.hourly.aggregate import Sample, aggregate, aggregate_hour, aqi_from_pm, expected_samples, hour_label
from app.modules.telemetry.qc import QcFlag

H14 = datetime(2026, 10, 15, 7, 0, tzinfo=UTC)  # 14:00 giờ Việt Nam


def s(at: datetime, *, excluded: bool = False, flags: int = 0, max_age_s: int | None = None, **values) -> Sample:
    """Mẫu đo tại `at`, nhận ngay lúc đó."""
    return Sample(measured_at=at, received_at=at, max_age_s=max_age_s, qc_flags=flags, excluded=excluded, **values)


def test_hour_label_window_is_left_open_right_closed():
    """Cửa sổ (h−1, h]: đúng HH:00:00 thuộc giờ HH, HH:00:01 thuộc giờ HH+1."""
    assert hour_label(H14) == H14
    assert hour_label(H14 + timedelta(seconds=1)) == H14 + timedelta(hours=1)
    assert hour_label(H14 - timedelta(microseconds=1)) == H14


def test_aggregate_splits_samples_by_window():
    out = aggregate([s(H14, pm25=10.0), s(H14 + timedelta(seconds=1), pm25=20.0)], 900, 1)
    assert list(out) == [H14, H14 + timedelta(hours=1)]
    assert out[H14].pm25_avg == 10.0
    assert out[H14 + timedelta(hours=1)].pm25_avg == 20.0


def test_excluded_samples_counted_but_not_averaged():
    """Mẫu cách ly/nghi cũ chỉ đếm vào n_excluded; không vào trung bình, max, số mẫu."""
    samples = [
        s(H14 - timedelta(minutes=30), pm25=10.0, pm10=20.0),
        s(H14 - timedelta(minutes=20), pm25=500.0, pm10=600.0, excluded=True, flags=QcFlag.UNTRUSTED_GATEWAY),
    ]
    agg = aggregate_hour(H14, samples, 900, 1)
    assert (agg.n_samples, agg.n_excluded, agg.pm25_avg, agg.pm25_max, agg.n_pm25) == (1, 1, 10.0, 10.0, 1)
    assert agg.qc_flags & QcFlag.UNTRUSTED_GATEWAY == 0


def test_only_excluded_samples_gives_row_without_values():
    """Giờ chỉ có mẫu bị loại vẫn có dòng (n_samples = 0) để biết giờ đó có dữ liệu cách ly."""
    agg = aggregate_hour(H14, [s(H14, pm25=10.0, pm10=10.0, excluded=True)], 900, 1)
    assert (agg.n_samples, agg.n_excluded, agg.pm25_avg, agg.aqi, agg.coverage) == (0, 1, None, None, 0.0)


def test_empty_hour_has_no_row():
    assert aggregate_hour(H14, [], 900, 1) is None
    assert aggregate([], 900, 1) == {}


@pytest.mark.parametrize(
    ("interval_s", "n", "expected", "coverage"),
    [
        (86_400, 1, 3600 / 86_400, 1.0),  # chu kỳ 1 ngày: expected ≈ 0,042, coverage kẹp về 1, không chia 0 (R27)
        (15, 120, 240.0, 0.5),
        (None, 3, None, None),  # chưa biết chu kỳ
    ],
)
def test_expected_samples_and_coverage(interval_s, n, expected, coverage):
    samples = [s(H14 - timedelta(seconds=10 * i), pm25=1.0) for i in range(n)]
    agg = aggregate_hour(H14, samples, interval_s, 1)
    assert agg.expected_samples == expected
    assert agg.coverage == coverage
    assert expected_samples(interval_s) == expected


def test_min_samples_per_variable():
    """Biến có ít mẫu hơn hourly_min_samples thì trung bình null, nhưng vẫn đếm n_*."""
    agg = aggregate_hour(H14, [s(H14, pm25=10.0, temperature=30.0)], 900, min_samples=2)
    assert (agg.pm25_avg, agg.n_pm25, agg.temperature_avg, agg.n_temperature) == (None, 1, None, 1)


def test_hourly_aqi_from_mean_pm_counterexample():
    """Mẫu 12,0 và 12,2 → PM2.5 trung bình 12,1 → AQI 51 (cột real sẽ cho 50, R9)."""
    samples = [s(H14 - timedelta(minutes=40), pm25=12.0, pm10=10.0), s(H14, pm25=12.2, pm10=10.0)]
    agg = aggregate_hour(H14, samples, 900, 1)
    assert agg.aqi == 51
    assert agg.aqi_pm25 == 51
    assert agg.aqi == int(compute_aqi(agg.pm25_avg, agg.pm10_avg))


def test_aqi_needs_both_pm():
    agg = aggregate_hour(H14, [s(H14, pm25=40.0)], 900, 1)
    assert (agg.aqi, agg.aqi_pm25, agg.aqi_pm10) == (None, 112, None)
    assert aqi_from_pm(None, 10.0) is None


def test_time_counters_and_flags():
    """n_time_estimated theo cờ; n_time_ambiguous khi khoảng thời điểm thật vắt qua ranh giới giờ (R6)."""
    near = H14 + timedelta(seconds=20)  # nhận 14:00:20, thuộc giờ 15:00
    samples = [
        s(near, flags=QcFlag.TIME_ESTIMATED | QcFlag.HIGH_HUMIDITY, max_age_s=60, pm25=1.0),  # có thể đo 13:59:20
        s(near + timedelta(seconds=5), max_age_s=10, pm25=1.0),  # chắc chắn sau 14:00
    ]
    agg = aggregate_hour(H14 + timedelta(hours=1), samples, 15, 1)
    assert (agg.n_time_estimated, agg.n_time_ambiguous) == (1, 1)
    assert agg.qc_flags == QcFlag.TIME_ESTIMATED | QcFlag.HIGH_HUMIDITY
