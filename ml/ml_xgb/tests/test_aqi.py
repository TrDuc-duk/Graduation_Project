import numpy as np
import pandas as pd
import pytest

from src import config
from src.aqi import aqi_pm10, aqi_pm25, compute_aqi
from src.data_loading import load_raw_dataset

# PM2.5, PM10, AQI PM2.5, AQI PM10, AQI (PLAN.md mục 13)
EXAMPLES = [
    (45.3, 82, 125, 64, 125),
    (25, 50, 78, 46, 78),
    (77.67, 109.3, 162, 78, 162),
    (71.9, 74.5, 159, 60, 159),
    (374.67, 521.7, 400, 408, 408),
]


@pytest.mark.parametrize("pm25,pm10,i25,i10,aqi", EXAMPLES)
def test_report_examples(pm25, pm10, i25, i10, aqi):
    assert aqi_pm25(pm25) == i25
    assert aqi_pm10(pm10) == i10
    assert compute_aqi(pm25, pm10) == aqi


@pytest.mark.parametrize(
    "pm25,expected",
    [(0, 0), (12.0, 50), (12.1, 51), (35.4, 100), (35.5, 101), (55.4, 150),
     (55.5, 151), (150.4, 200), (150.5, 201), (250.4, 300), (250.5, 301), (500.4, 500)],
)
def test_pm25_breakpoints(pm25, expected):
    assert aqi_pm25(pm25) == expected


@pytest.mark.parametrize(
    "pm10,expected",
    [(0, 0), (54, 50), (55, 51), (154, 100), (155, 101), (254, 150),
     (255, 151), (354, 200), (355, 201), (424, 300), (425, 301), (604, 500)],
)
def test_pm10_breakpoints(pm10, expected):
    assert aqi_pm10(pm10) == expected


def test_truncation_not_rounding():
    # 12.09 phải cắt thành 12.0 (AQI 50), không làm tròn thành 12.1 (AQI 51)
    assert aqi_pm25(12.09) == 50
    # 54.9 cắt thành 54 (AQI 50), không làm tròn thành 55
    assert aqi_pm10(54.9) == 50


def test_round_half_up():
    # .5 làm tròn lên (không dùng banker's rounding của round())
    from src.aqi import _round_half_up

    assert _round_half_up(np.array([2.5, 3.5, 0.5, 124.5])).tolist() == [3, 4, 1, 125]


def test_over_range_caps_at_500():
    assert aqi_pm25(900) == 500
    assert aqi_pm10(1103) == 500
    assert compute_aqi(10, 1103) == 500


def test_nan_propagates_and_series():
    s25 = pd.Series([45.3, np.nan], index=[5, 6])
    s10 = pd.Series([82, 50], index=[5, 6])
    out = compute_aqi(s25, s10)
    assert out.iloc[0] == 125
    assert np.isnan(out.iloc[1])
    assert out.index.tolist() == [5, 6]


def test_matches_dataset_csv_column():
    """AQI trong CSV đã được tính lại theo quy tắc này -> phải khớp toàn bộ 41.112 dòng."""
    df = load_raw_dataset(config.DATA_PATH)
    recomputed = compute_aqi(df["pm2_5"], df["pm10"])
    assert (recomputed.values == df["AQI"].values).all()
