import numpy as np
import pandas as pd
import pytest

from rf import config
from rf.predict import available_horizons, predict
from rf.train import (build_metadata, load_model_and_metadata, save_model_and_metadata,
                      train_one_horizon, verify_reload_consistency)
from rf.tune import grid, select_best
from src.feature_engineering import build_feature_matrix, get_feature_columns
from src.predict import InferenceDataError
from src.preprocessing import build_hourly_grid
from src.train import build_dataset

T = pd.Timestamp
SMALL = {"n_estimators": 20, "min_samples_leaf": 5, "n_jobs": 1}
BOUNDS = {"train_start": T("2024-01-01 00:00"), "train_end": T("2024-02-10 00:00"),
          "val_end": T("2024-02-25 00:00"), "test_end": T("2024-03-04 12:00")}


def _raw(n=1500, seed=7):
    rng = np.random.default_rng(seed)
    times = pd.date_range("2024-01-01 00:00", periods=n, freq="1h")
    aqi = 100 + 40 * np.sin(2 * np.pi * times.hour.to_numpy() / 24) + rng.normal(0, 5, n)
    return pd.DataFrame({"time": times, "AQI": aqi.round(), "pm10": rng.uniform(20, 120, n),
                         "pm2_5": rng.uniform(10, 80, n), "Humidity": rng.uniform(50, 95, n),
                         "Temperature": rng.uniform(15, 30, n)})


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    d = tmp_path_factory.mktemp("rf_models")
    data, aqi, _ = build_dataset(raw=_raw(), horizons=[3, 6])
    cols = get_feature_columns()
    results = {}
    for h in (3, 6):
        res = train_one_horizon(data, aqi, h, cols, SMALL, bounds=BOUNDS, evaluate_test=(h == 3))
        meta = build_metadata(res, cols, "x", BOUNDS)
        save_model_and_metadata(res["model"], meta, d)
        results[h] = (res, meta)
    return data, cols, d, results


def test_learns_seasonal_signal_better_than_mean24(trained):
    _, _, _, results = trained
    val = {r["method"]: r for r in results[3][0]["rows"] if r["segment"] == "val"}
    assert set(val) == {"random_forest", "persistence", "mean_24h", "same_hour_of_day"}
    assert val["random_forest"]["MAE"] < val["mean_24h"]["MAE"]


def test_model_and_baselines_share_samples_and_test_only_when_asked(trained):
    _, _, _, results = trained
    for h, (res, _) in results.items():
        segs = {r["segment"] for r in res["rows"]}
        assert segs == ({"val", "test"} if h == 3 else {"val"})
        for seg in segs:
            assert len({r["n"] for r in res["rows"] if r["segment"] == seg}) == 1


def test_reload_parity_and_metadata(trained):
    data, cols, d, results = trained
    res, meta = results[3]
    assert verify_reload_consistency(res["model"], meta, data.dropna(subset=cols).tail(100), d)
    _, meta2 = load_model_and_metadata(3, d)
    assert meta2["feature_columns"] == cols
    assert meta2["required_history_hours"] == 73 and meta2["nan_policy"]["name"] == "no_fill"
    assert not any(c.startswith("target_") for c in meta2["feature_columns"])


def test_predict_matches_model_on_training_row(trained):
    _, cols, d, _ = trained
    raw = _raw()
    t = T("2024-02-20 13:00")
    out = predict(raw, t=t, node_id="NODE_076", models_dir=d)
    assert out["horizon_hours"].tolist() == [3, 6] == available_horizons(d)
    assert (out["target_time"] == t + pd.to_timedelta(out["horizon_hours"], unit="h")).all()
    model, meta = load_model_and_metadata(3, d)
    X = build_feature_matrix(build_hourly_grid(raw)).set_index("time").loc[[t], meta["feature_columns"]]
    assert out["predicted_aqi"].iloc[0] == pytest.approx(float(model.predict(X)[0]))


def test_predict_rejects_short_history(trained):
    _, _, d, _ = trained
    with pytest.raises(InferenceDataError):
        predict(_raw().head(40), models_dir=d)


def test_tune_grid_and_selection():
    assert len(grid({"a": [1, 2], "b": [3, 4, 5]})) == 6
    res = pd.DataFrame({"min_samples_leaf": [5, 5, 10, 10], "max_features": [0.2, 0.2, 0.5, 0.5],
                        "horizon": [3, 24, 3, 24], "val_MAE": [1, 1, 1, 1],
                        "val_RMSE": [10.0, 12.0, 9.0, 11.0], "train_MAE": [1, 1, 1, 1]})
    best, summary = select_best(res, ["min_samples_leaf", "max_features"])
    assert best == {"min_samples_leaf": 10, "max_features": 0.5}
    assert isinstance(best["min_samples_leaf"], int)


def test_config_reuses_xgb_split_and_horizons():
    from src import config as base
    assert config.HORIZONS == base.HORIZONS == list(range(3, 73, 3))
    assert config.MODELS_DIR.name == "models" and config.MODELS_DIR.parent.name == "ml_rf"
