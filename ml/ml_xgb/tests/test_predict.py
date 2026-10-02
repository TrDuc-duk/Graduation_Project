import numpy as np
import pandas as pd
import pytest

from src import config
from src.feature_engineering import build_feature_matrix, get_feature_columns
from src.predict import InferenceDataError, available_horizons, build_inference_features, predict
from src.preprocessing import build_hourly_grid
from src.train import (build_dataset, build_metadata, predict_with_model, required_history_hours,
                       save_model_and_metadata, train_one_horizon)

T = pd.Timestamp
SMALL_PARAMS = {**config.XGB_PARAMS, "n_estimators": 40, "learning_rate": 0.1, "max_depth": 3}
BOUNDS = {"train_start": T("2024-01-01 00:00"), "train_end": T("2024-02-10 00:00"),
          "val_end": T("2024-02-25 00:00"), "test_end": T("2024-03-04 12:00")}


def _raw(n=1500, seed=3):
    rng = np.random.default_rng(seed)
    times = pd.date_range("2024-01-01 00:00", periods=n, freq="1h")
    aqi = 100 + 40 * np.sin(2 * np.pi * times.hour.to_numpy() / 24) + rng.normal(0, 5, n)
    return pd.DataFrame({"time": times, "AQI": aqi.round(), "pm10": rng.uniform(20, 120, n),
                         "pm2_5": rng.uniform(10, 80, n), "Humidity": rng.uniform(50, 95, n),
                         "Temperature": rng.uniform(15, 30, n)})


@pytest.fixture(scope="module")
def models_dir(tmp_path_factory):
    d = tmp_path_factory.mktemp("models")
    data, aqi, policy_meta = build_dataset(raw=_raw(), horizons=[3, 6])
    cols = get_feature_columns()
    for h in (3, 6):
        res = train_one_horizon(data, aqi, h, cols, params=SMALL_PARAMS, bounds=BOUNDS, early_stopping_rounds=5)
        save_model_and_metadata(res["model"], build_metadata(res, cols, policy_meta, "x", BOUNDS), d)
    return d


def _meta(models_dir, h=3):
    from src.train import load_model_and_metadata
    return load_model_and_metadata(h, models_dir)


def test_required_history_hours():
    assert required_history_hours() == 73  # t-72 .. t


def test_inference_features_match_training_features(models_dir):
    raw = _raw()
    _, meta = _meta(models_dir)
    t = T("2024-02-20 13:00")
    train_row = build_feature_matrix(build_hourly_grid(raw)).set_index("time").loc[t, meta["feature_columns"]]
    inf_row = build_inference_features(raw, meta, t).set_index("time").loc[t, meta["feature_columns"]]
    pd.testing.assert_series_equal(train_row, inf_row, check_names=False)


def test_future_rows_are_ignored(models_dir):
    raw = _raw()
    _, meta = _meta(models_dir)
    t = T("2024-02-20 13:00")
    tampered = raw.copy()
    tampered.loc[tampered["time"] > t, ["AQI", "pm10"]] = 9999.0
    a = build_inference_features(raw, meta, t)
    b = build_inference_features(tampered, meta, t)
    pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))


def test_insufficient_history_raises(models_dir):
    raw = _raw()
    _, meta = _meta(models_dir)
    with pytest.raises(InferenceDataError):
        build_inference_features(raw.head(50), meta)  # < 73 giờ
    gap = raw[(raw["time"] < T("2024-02-20 10:00")) | (raw["time"] > T("2024-02-20 11:00"))]
    with pytest.raises(InferenceDataError):  # lỗ 2 giờ trong cửa sổ 72h -> rolling thiếu
        build_inference_features(gap, meta, T("2024-02-20 13:00"))


def test_stale_data_raises(models_dir):
    raw = _raw()
    _, meta = _meta(models_dir)
    t = raw["time"].max()
    with pytest.raises(InferenceDataError):
        build_inference_features(raw, meta, now=t + pd.Timedelta(hours=5))
    build_inference_features(raw, meta, now=t + pd.Timedelta(hours=1))


def test_predict_output_contract(models_dir):
    raw = _raw()
    t = T("2024-02-20 13:00")
    out = predict(raw, t=t, node_id="NODE_076", models_dir=models_dir)
    assert list(out.columns) == ["node_id", "input_time", "target_time", "horizon_hours",
                                 "predicted_aqi", "model_version"]
    assert out["horizon_hours"].tolist() == [3, 6] == available_horizons(models_dir)
    assert (out["target_time"] == t + pd.to_timedelta(out["horizon_hours"], unit="h")).all()


def test_predict_equals_model_on_training_row(models_dir):
    raw = _raw()
    model, meta = _meta(models_dir)
    t = T("2024-02-20 13:00")
    X = build_feature_matrix(build_hourly_grid(raw)).set_index("time").loc[[t], meta["feature_columns"]]
    expected = predict_with_model(model, X, meta["n_trees"])[0]
    got = predict(raw, horizons=[3], t=t, models_dir=models_dir)["predicted_aqi"].iloc[0]
    assert got == pytest.approx(float(expected))
