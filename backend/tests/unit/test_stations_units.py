"""Phần thuần Python của stations và bảng mức AQI: nhận diện trạm, xu hướng, tóm tắt."""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.aqi_scale import LEVELS, level_of
from app.modules.stations.service import (
    DECREASING,
    INCREASING,
    INSUFFICIENT,
    STABLE,
    Ambiguous,
    Found,
    NotFound,
    match_station,
    normalize_name,
    summarize,
    trend,
)

T0 = datetime(2026, 10, 15, 0, 0, tzinfo=UTC)
FRONTEND_AQI = Path(__file__).resolve().parents[3] / "frontend" / "src" / "lib" / "aqi.ts"


@pytest.mark.parametrize(
    ("aqi", "key"),
    [
        (0, "good"),
        (50, "good"),
        (51, "moderate"),
        (101, "usg"),
        (151, "unhealthy"),
        (300, "very_unhealthy"),
        (301, "hazardous"),
        (650, "hazardous"),
    ],
)
def test_level_of_uses_us_epa_breakpoints(aqi, key):
    assert level_of(aqi).key == key


def test_level_of_none_stays_none():
    assert level_of(None) is None


@pytest.mark.skipif(not FRONTEND_AQI.exists(), reason="không có mã frontend")
def test_labels_match_frontend_scale():
    """Nhãn mức AQI của backend trùng nhãn hiển thị trên web (một nội dung cho cả web và chatbot)."""
    frontend_labels = re.findall(r'label: "([^"]+)"', FRONTEND_AQI.read_text(encoding="utf-8"))
    assert frontend_labels == [level.label for level in LEVELS]


def station(code: str, name: str) -> SimpleNamespace:
    return SimpleNamespace(station_code=code, name=name)


STATIONS = [station("ST001", "Bách Khoa"), station("ST002", "Đống Đa"), station("ST003", "Bách Khoa 2")]


def test_normalize_name_drops_accents_and_prefix():
    assert normalize_name("  Trạm   Bách  Khoa ") == "bach khoa"
    assert normalize_name("ĐỐNG ĐA") == "dong da"


def test_match_by_code_ignores_case():
    assert match_station(STATIONS, "st002") == Found(STATIONS[1])


def test_exact_name_wins_over_partial():
    assert match_station(STATIONS, "trạm bách khoa") == Found(STATIONS[0])


def test_partial_name_matching_one_station():
    assert match_station(STATIONS, "dong") == Found(STATIONS[1])


def test_partial_name_matching_many_is_ambiguous():
    assert match_station(STATIONS, "bach") == Ambiguous([STATIONS[0], STATIONS[2]])


def test_unknown_or_empty_ref_not_found():
    assert match_station(STATIONS, "Cầu Giấy") == NotFound("Cầu Giấy")
    assert match_station(STATIONS, "trạm") == NotFound("trạm")


def series(values: list[float], step_min: int = 10) -> list[tuple[datetime, float]]:
    return [(T0 + timedelta(minutes=i * step_min), v) for i, v in enumerate(values)]


def test_trend_needs_six_values():
    assert trend(series([10, 50, 90, 130, 170])) == INSUFFICIENT


def test_trend_compares_last_third_with_first_third():
    assert trend(series([50, 52, 60, 70, 80, 85])) == INCREASING
    assert trend(series([120, 118, 100, 90, 80, 79])) == DECREASING
    assert trend(series([50, 55, 48, 52, 57, 54])) == STABLE  # chênh dưới 10


def test_trend_same_timestamp_is_insufficient():
    assert trend([(T0, v) for v in [1, 2, 3, 4, 5, 6]]) == INSUFFICIENT


def row(minutes: int, aqi=None, pm25=None, pm10=None, temperature=None, humidity=None) -> SimpleNamespace:
    return SimpleNamespace(
        measured_at=T0 + timedelta(minutes=minutes),
        aqi_instant=aqi,
        pm25=pm25,
        pm10=pm10,
        temperature=temperature,
        humidity=humidity,
    )


def test_summarize_skips_nulls_and_reports_real_span():
    rows = [row(0, aqi=100, pm25=30.0, humidity=None), row(30, aqi=None, pm25=None), row(60, aqi=110, pm25=40.0)]
    s = summarize(rows, since=T0 - timedelta(hours=24))
    assert (s.n_samples, s.first_at, s.last_at) == (3, T0, T0 + timedelta(hours=1))
    assert (s.metrics["aqi"].avg, s.metrics["aqi"].min, s.metrics["aqi"].max, s.metrics["aqi"].n) == (
        105.0,
        100,
        110,
        2,
    )
    assert s.metrics["aqi"].trend == INSUFFICIENT
    assert (s.metrics["humidity"].avg, s.metrics["humidity"].n, s.metrics["humidity"].trend) == (None, 0, None)


def test_summarize_empty_window():
    s = summarize([], since=T0)
    assert (s.n_samples, s.first_at, s.metrics["pm25"].avg) == (0, None, None)
