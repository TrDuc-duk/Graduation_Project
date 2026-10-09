import numpy as np
import pandas as pd

from src import config
from src.data_loading import load_raw_dataset
from src.feature_engineering import build_feature_matrix, get_feature_columns
from src.preprocessing import build_hourly_grid
from src.split import (bounds_from_ratios, count_samples_by_source, label_segment,
                       legacy_only_bounds, select_valid_samples)
from src.targets import add_targets, target_column

T = pd.Timestamp


def _real_grid():
    return add_targets(build_hourly_grid(load_raw_dataset(config.DATA_PATH)))


def test_config_cutoffs_match_floor_ratios_on_full_grid():
    g = build_hourly_grid(load_raw_dataset(config.DATA_PATH))
    b = bounds_from_ratios(g["time"])
    assert b["train_start"] == config.TRAIN_START
    assert b["train_end"] == config.TRAIN_END
    assert b["val_end"] == config.VAL_END
    assert b["test_end"] == config.TEST_END


def test_label_segment_boundaries_half_open():
    times = pd.Series([
        config.TRAIN_START - pd.Timedelta(hours=1), config.TRAIN_START,
        config.TRAIN_END - pd.Timedelta(hours=1), config.TRAIN_END,
        config.VAL_END - pd.Timedelta(hours=1), config.VAL_END,
        config.TEST_END - pd.Timedelta(hours=1), config.TEST_END,
    ])
    assert label_segment(times).tolist() == [None, "train", "train", "val", "val", "test", "test", None]


def test_sample_dropped_when_target_crosses_boundary():
    g = _real_grid()
    cols = get_feature_columns()
    data = pd.concat([build_feature_matrix(g), g[[target_column(3)]]], axis=1)
    train, log = select_valid_samples(data, 3, "train", cols)
    # t + 3h phải < TRAIN_END: mẫu cuối hợp lệ là TRAIN_END - 4h; 3 mẫu cuối đoạn bị loại
    assert train["time"].max() == config.TRAIN_END - pd.Timedelta(hours=4)
    assert log["dropped_label_outside_segment"] == 3


def test_no_overlap_and_labels_inside_segment_for_all_horizons():
    g = _real_grid()
    cols = get_feature_columns()
    X = build_feature_matrix(g)
    bounds_by_seg = {"train": (config.TRAIN_START, config.TRAIN_END),
                     "val": (config.TRAIN_END, config.VAL_END),
                     "test": (config.VAL_END, config.TEST_END)}
    for h in (3, 24, 72):
        data = pd.concat([X, g[[target_column(h)]]], axis=1)
        seen = []
        for seg, (lo, hi) in bounds_by_seg.items():
            s, log = select_valid_samples(data, h, seg, cols)
            tt = s["time"] + pd.Timedelta(hours=h)
            assert (s["time"] >= lo).all() and (s["time"] < hi).all()
            assert (tt >= lo).all() and (tt < hi).all()  # nhãn cũng nằm trong đoạn
            assert not s[cols].isna().any().any() and not s[target_column(h)].isna().any()
            assert log["kept"] == len(s) > 0
            seen.append(set(s["time"]))
        assert not (seen[0] & seen[1]) and not (seen[1] & seen[2]) and not (seen[0] & seen[2])


def test_missing_day_samples_dropped_with_reasons():
    g = _real_grid()
    cols = get_feature_columns()
    data = pd.concat([build_feature_matrix(g), g[[target_column(24)]]], axis=1)
    train, log = select_valid_samples(data, 24, "train", cols)
    gap = pd.date_range("2023-12-31", periods=24, freq="1h")
    assert not train["time"].isin(gap).any()
    assert log["dropped_missing_target"] >= 24  # t+24h rơi vào ngày thiếu
    assert log["dropped_missing_feature"] > 0
    assert log["kept"] + log["dropped_missing_target"] + log["dropped_missing_feature"] \
        + log["dropped_label_outside_segment"] == log["rows_with_t_in_segment"]


def test_source_counts_and_legacy_bounds():
    g = _real_grid()
    cols = get_feature_columns()
    data = pd.concat([build_feature_matrix(g), g[[target_column(3)]]], axis=1)
    test, _ = select_valid_samples(data, 3, "test", cols)
    c = count_samples_by_source(test)
    assert c["open_meteo"] == len(test) and c["legacy"] == 0  # test hoàn toàn là Open-Meteo
    lb = legacy_only_bounds(g["time"])
    assert lb["test_end"] == config.SOURCE_SWITCH and lb["train_end"] < lb["val_end"] < lb["test_end"]
    leg, _ = select_valid_samples(data, 3, "test", cols, bounds=lb)
    assert (leg["time"] + pd.Timedelta(hours=3) < config.SOURCE_SWITCH).all() and len(leg) > 0
