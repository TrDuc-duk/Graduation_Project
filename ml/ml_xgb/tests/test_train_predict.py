import numpy as np
import pandas as pd
import pytest

from src import config
from src.feature_engineering import get_feature_columns
from src.train import (build_dataset, build_metadata, load_model_and_metadata, predict_with_model,
                       save_model_and_metadata, train_one_horizon, verify_reload_consistency)

T = pd.Timestamp
SMALL_PARAMS = {**config.XGB_PARAMS, "n_estimators": 60, "learning_rate": 0.1, "max_depth": 4}


def _raw(n=1500, seed=1):
    rng = np.random.default_rng(seed)
    times = pd.date_range("2024-01-01 00:00", periods=n, freq="1h")
    hour = times.hour.to_numpy()
    aqi = 100 + 40 * np.sin(2 * np.pi * hour / 24) + rng.normal(0, 5, n)
    df = pd.DataFrame({"time": times, "AQI": aqi.round(), "pm10": rng.uniform(20, 120, n),
                       "pm2_5": rng.uniform(10, 80, n), "Humidity": rng.uniform(50, 95, n),
                       "Temperature": rng.uniform(15, 30, n)})
    return df.drop(index=range(700, 710)).reset_index(drop=True)  # thủng 10 giờ


BOUNDS = {"train_start": T("2024-01-01 00:00"), "train_end": T("2024-02-10 00:00"),
          "val_end": T("2024-02-25 00:00"), "test_end": T("2024-03-04 12:00")}


@pytest.fixture(scope="module")
def trained():
    data, aqi_grid, policy_meta = build_dataset(raw=_raw(), horizons=[3, 27])
    cols = get_feature_columns()
    res = train_one_horizon(data, aqi_grid, 3, cols, params=SMALL_PARAMS, bounds=BOUNDS,
                            early_stopping_rounds=10)
    return data, aqi_grid, policy_meta, cols, res


def test_pipeline_runs_and_beats_naive_on_seasonal_signal(trained):
    *_, res = trained
    val = {r["method"]: r for r in res["rows"] if r["segment"] == "val"}
    assert set(val) == {"xgboost", "persistence", "mean_24h", "same_hour_of_day"}
    assert val["xgboost"]["MAE"] < val["mean_24h"]["MAE"]
    assert res["n_trees"] == res["best_iteration"] + 1


def test_test_segment_not_evaluated_by_default(trained):
    *_, res = trained
    assert {r["segment"] for r in res["rows"]} == {"val"}


def test_evaluate_test_flag_adds_test_rows(trained):
    data, aqi_grid, _, cols, _ = trained
    res = train_one_horizon(data, aqi_grid, 3, cols, params=SMALL_PARAMS, bounds=BOUNDS,
                            early_stopping_rounds=10, evaluate_test=True)
    assert {r["segment"] for r in res["rows"]} == {"val", "test"}


def test_model_and_baselines_share_same_samples(trained):
    *_, res = trained
    by_seg = {}
    for r in res["rows"]:
        by_seg.setdefault(r["segment"], set()).add(r["n"])
    assert all(len(s) == 1 for s in by_seg.values())  # cùng n cho mọi phương pháp


def test_features_exclude_targets(trained):
    _, _, _, cols, _ = trained
    assert not any(c.startswith("target_") for c in cols)


def test_save_reload_prediction_parity(trained, tmp_path):
    data, _, policy_meta, cols, res = trained
    meta = build_metadata(res, cols, policy_meta, "deadbeef", BOUNDS)
    save_model_and_metadata(res["model"], meta, tmp_path)
    assert verify_reload_consistency(res["model"], meta, data.dropna(subset=cols).tail(200), tmp_path)
    reloaded, meta2 = load_model_and_metadata(3, tmp_path)
    assert meta2["feature_columns"] == cols and meta2["horizon_hours"] == 3
    assert meta2["nan_policy"]["name"] == "no_fill" and meta2["refit_on_train_val"] is False
    X = data.dropna(subset=cols).tail(50)[cols]
    np.testing.assert_allclose(predict_with_model(res["model"], X, meta["n_trees"]),
                               predict_with_model(reloaded, X, meta2["n_trees"]))


def test_refit_uses_best_iteration_trees(trained):
    data, aqi_grid, _, cols, base = trained
    res = train_one_horizon(data, aqi_grid, 3, cols, params=SMALL_PARAMS, bounds=BOUNDS,
                            early_stopping_rounds=10, refit=True)
    assert res["refit"] and res["model"].get_booster().num_boosted_rounds() == base["n_trees"]
