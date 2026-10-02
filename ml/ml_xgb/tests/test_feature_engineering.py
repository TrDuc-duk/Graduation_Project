import numpy as np
import pandas as pd
import pytest

from src import config
from src.data_loading import load_raw_dataset
from src.feature_engineering import build_feature_matrix, get_feature_columns
from src.preprocessing import apply_nan_policy, build_hourly_grid
from src.targets import add_targets, target_column


def _synthetic_grid(n=200, seed=0):
    rng = np.random.default_rng(seed)
    times = pd.date_range("2024-03-01 00:00", periods=n, freq="1h")
    df = pd.DataFrame({
        "time": times,
        "AQI": rng.integers(20, 300, n).astype(float),
        "pm10": rng.uniform(10, 200, n), "pm2_5": rng.uniform(5, 150, n),
        "Humidity": rng.uniform(40, 100, n), "Temperature": rng.uniform(10, 35, n),
    })
    return build_hourly_grid(df)


def test_lag_rolling_diff_hand_computed():
    g = _synthetic_grid()
    X = build_feature_matrix(g)
    t = 100
    aqi = g["AQI"]
    assert X.loc[t, "AQI"] == aqi[t]
    assert X.loc[t, "AQI_lag24"] == aqi[t - 24]
    assert X.loc[t, "AQI_diff6"] == aqi[t] - aqi[t - 6]
    assert X.loc[t, "AQI_roll3_mean"] == pytest.approx(aqi[t - 2: t + 1].mean())
    assert X.loc[t, "AQI_roll24_max"] == aqi[t - 23: t + 1].max()
    assert X.loc[t, "AQI_roll72_std"] == pytest.approx(aqi[t - 71: t + 1].std())
    # cửa sổ chưa đủ -> NaN (min_periods=w)
    assert np.isnan(X.loc[10, "AQI_roll24_mean"])
    assert np.isnan(X.loc[10, "AQI_lag24"])


def test_time_features_use_local_time():
    g = _synthetic_grid()
    X = build_feature_matrix(g)
    assert X.loc[5, "hour"] == 5
    assert X.loc[0, "month"] == 3
    assert X.loc[6, "hour_sin"] == pytest.approx(1.0)


def test_features_at_t_unchanged_when_future_data_modified():
    g = _synthetic_grid()
    t = 120
    X1 = build_feature_matrix(g).loc[t]
    g2 = g.copy()
    g2.loc[t + 1:, config.BASE_COLUMNS] = -999.0
    g2.loc[t + 1:, "AQI_observed"] = -999.0
    X2 = build_feature_matrix(g2).loc[t]
    pd.testing.assert_series_equal(X1, X2)


def test_feature_columns_explicit_and_no_target_leak():
    for policy in ("no_fill", "ffill3h"):
        cols = get_feature_columns(policy)
        assert not any(c.startswith("target_") for c in cols)
        assert len(cols) == len(set(cols))
    X = build_feature_matrix(_synthetic_grid())
    assert list(X.columns) == ["time"] + get_feature_columns()


def test_ffill_policy_columns_present():
    g, _ = apply_nan_policy(_synthetic_grid(), "ffill3h")
    X = build_feature_matrix(g, policy="ffill3h")
    assert "AQI_is_filled" in X and "pm10_age_hours" in X


def test_future_time_features_named_per_horizon():
    g = _synthetic_grid()
    X = build_feature_matrix(g, include_future_time=True, h=27)
    assert X.loc[0, "hour_h27"] == (0 + 27) % 24
    assert "hour_h27" in X.columns and "hour_h3" not in X.columns


def test_noncontiguous_grid_rejected():
    g = _synthetic_grid().drop(index=[5]).reset_index(drop=True)
    with pytest.raises(ValueError):
        build_feature_matrix(g)


def test_targets_shift_on_synthetic():
    g = add_targets(_synthetic_grid(), horizons=[3, 24])
    assert g.loc[10, target_column(3)] == g.loc[13, "AQI"]
    assert np.isnan(g[target_column(24)].iloc[-24:]).all()


def test_targets_near_real_gap():
    g = add_targets(build_hourly_grid(load_raw_dataset(config.DATA_PATH)))
    by_time = g.set_index("time")["AQI_observed"]
    gap = pd.date_range("2023-12-31 00:00", "2023-12-31 23:00", freq="1h")
    for h in (3, 24, 72):
        col = target_column(h)
        # t sao cho t+h rơi vào ngày thiếu -> nhãn NaN
        t_in = gap - pd.Timedelta(hours=h)
        assert g.set_index("time").loc[t_in, col].isna().all()
        # nhãn luôn đúng bằng AQI tại đúng timestamp t+h (kể cả quanh khoảng thiếu)
        sample = g[(g["time"] >= "2023-12-27") & (g["time"] <= "2024-01-05")]
        expected = by_time.reindex(sample["time"] + pd.Timedelta(hours=h)).values
        np.testing.assert_array_equal(sample[col].values, expected)


def test_extra_features_no_future_leak_and_columns():
    g = _synthetic_grid()
    t = 120
    X1 = build_feature_matrix(g, include_extra=True)
    assert list(X1.columns) == ["time"] + get_feature_columns(include_extra=True)
    g2 = g.copy()
    g2.loc[t + 1:, config.BASE_COLUMNS] = -999.0
    X2 = build_feature_matrix(g2, include_extra=True)
    pd.testing.assert_series_equal(X1.loc[t], X2.loc[t])
    assert X1.loc[t, "AQI_ewm6"] == pytest.approx(g["AQI"][: t + 1].ewm(span=6, adjust=False).mean()[t])
    assert np.isnan(X1.loc[3, "AQI_ewm24"])


def test_extra_ewm_nan_after_gap():
    g = _synthetic_grid()
    g.loc[50:52, config.BASE_COLUMNS] = np.nan
    X = build_feature_matrix(g, include_extra=True)
    assert X.loc[53:57, "AQI_ewm6"].isna().all() and not np.isnan(X.loc[58, "AQI_ewm6"])
