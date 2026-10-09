import numpy as np
import pandas as pd

from src import config
from src.experiments import CONFIGS, common_val_index, run_config, walk_forward_bounds
from src.train import build_dataset

T = pd.Timestamp
SMALL = {"n_estimators": 40, "learning_rate": 0.1, "max_depth": 3}
BOUNDS = {"train_start": T("2024-01-01 00:00"), "train_end": T("2024-02-10 00:00"),
          "val_end": T("2024-02-25 00:00"), "test_end": T("2024-02-25 00:00")}


def _raw(n=1300, seed=5):
    rng = np.random.default_rng(seed)
    times = pd.date_range("2024-01-01 00:00", periods=n, freq="1h")
    aqi = 100 + 40 * np.sin(2 * np.pi * times.hour.to_numpy() / 24) + rng.normal(0, 5, n)
    df = pd.DataFrame({"time": times, "AQI": aqi.round(), "pm10": rng.uniform(20, 120, n),
                       "pm2_5": rng.uniform(10, 80, n), "Humidity": rng.uniform(50, 95, n),
                       "Temperature": rng.uniform(15, 30, n)})
    return df.drop(index=range(300, 305)).reset_index(drop=True)


def test_walk_forward_folds_are_contiguous_and_before_test():
    times = pd.Series(pd.date_range(config.TRAIN_START, config.TEST_END, freq="1h", inclusive="left"))
    folds = walk_forward_bounds(times)
    assert len(folds) == 4
    for a, b in zip(folds, folds[1:]):
        assert a["val_end"] == b["train_end"]  # fold sau mở rộng train tới hết val fold trước
    assert all(f["val_end"] <= config.VAL_END for f in folds)


def test_all_configs_evaluated_on_identical_val_samples():
    data, _, _ = build_dataset(raw=_raw(), horizons=[3], include_extra=True)
    idx = common_val_index(data, 3, BOUNDS)
    n_vals = set()
    for name, cfg in CONFIGS.items():
        r = run_config(data, 3, cfg, SMALL, bounds=BOUNDS, seeds=(1,), val_index=idx,
                       early_stopping_rounds=5)
        n_vals.add(r["n_val"])
        assert (r["val"].index == idx).all()
    assert n_vals == {len(idx)}


def test_native_nan_keeps_more_train_rows_and_delta_adds_back_base():
    data, _, _ = build_dataset(raw=_raw(), horizons=[3], include_extra=True)
    idx = common_val_index(data, 3, BOUNDS)
    full = run_config(data, 3, CONFIGS["E0_baseline"], SMALL, bounds=BOUNDS, seeds=(1,), val_index=idx,
                      early_stopping_rounds=5)
    nan = run_config(data, 3, CONFIGS["E4_native_nan"], SMALL, bounds=BOUNDS, seeds=(1,), val_index=idx,
                     early_stopping_rounds=5)
    assert nan["n_train"] > full["n_train"]
    delta = run_config(data, 3, CONFIGS["E1_delta_target"], SMALL, bounds=BOUNDS, seeds=(1,),
                       val_index=idx, early_stopping_rounds=5)
    # dự báo delta đã cộng lại AQI(t) -> cùng thang đo với nhãn
    assert abs(np.mean(delta["val_pred_mean"]) - np.mean(full["val_pred_mean"])) < 20
