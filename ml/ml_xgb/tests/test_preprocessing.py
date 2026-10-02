import numpy as np
import pandas as pd

from src import config
from src.data_loading import load_raw_dataset
from src.preprocessing import apply_nan_policy, build_hourly_grid, sort_and_dedupe


def _frame(times):
    n = len(times)
    return pd.DataFrame({
        "time": pd.to_datetime(times),
        "AQI": np.arange(n, dtype=float) + 100,
        "pm10": 1.0, "pm2_5": 2.0, "Humidity": 3.0, "Temperature": 4.0,
    })


def test_grid_fills_gap_and_marks_unobserved():
    df = _frame(["2024-01-01 00:00", "2024-01-01 01:00", "2024-01-01 04:00"])
    g = build_hourly_grid(df)
    assert len(g) == 5
    assert g["observed"].tolist() == [True, True, False, False, True]
    assert g["AQI"].isna().tolist() == [False, False, True, True, False]
    assert (g["time"].diff().dropna() == pd.Timedelta(hours=1)).all()


def test_dedupe_keeps_first_and_sorts():
    df = _frame(["2024-01-01 01:00", "2024-01-01 00:00", "2024-01-01 01:00"])
    out, n = sort_and_dedupe(df)
    assert n == 1 and len(out) == 2
    assert out["time"].is_monotonic_increasing


def test_aqi_observed_never_filled_by_ffill():
    df = _frame(["2024-01-01 00:00", "2024-01-01 04:00"])
    g = build_hourly_grid(df)
    out, meta = apply_nan_policy(g, "ffill3h")
    # giờ 1,2,3 được điền cho đầu vào, nhưng nhãn gốc vẫn NaN
    assert out["AQI"].iloc[1:4].tolist() == [100.0] * 3
    assert out["AQI_observed"].iloc[1:4].isna().all()
    assert out["AQI_is_filled"].tolist() == [0, 1, 1, 1, 0]
    assert out["AQI_age_hours"].tolist() == [0, 1, 2, 3, 0]
    assert meta["ffill_limit_hours"] == 3


def test_ffill_limit_leaves_long_gap_as_nan():
    df = _frame(["2024-01-01 00:00", "2024-01-01 06:00"])
    out, _ = apply_nan_policy(build_hourly_grid(df), "ffill3h")
    assert out["AQI"].iloc[1:4].notna().all()
    assert out["AQI"].iloc[4:6].isna().all()  # giờ thứ 4, 5 vượt giới hạn 3h


def test_no_fill_is_identity_on_values():
    df = _frame(["2024-01-01 00:00", "2024-01-01 03:00"])
    g = build_hourly_grid(df)
    out, _ = apply_nan_policy(g, "no_fill")
    pd.testing.assert_frame_equal(out, g)


def test_real_dataset_grid_has_41136_rows_and_gap_on_2023_12_31():
    g = build_hourly_grid(load_raw_dataset(config.DATA_PATH))
    assert len(g) == 41136
    missing = g.loc[~g["observed"], "time"]
    expected = pd.date_range("2023-12-31 00:00", "2023-12-31 23:00", freq="1h")
    assert missing.tolist() == expected.tolist()
    assert g.loc[g["observed"], config.BASE_COLUMNS].notna().all().all()
