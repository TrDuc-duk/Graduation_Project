import pandas as pd
import pytest

from src import config
from src.data_loading import compute_file_sha256, load_raw_dataset, verify_dataset_hash


def test_parses_both_timestamp_formats(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text(
        "time,AQI,pm10,pm2_5,Humidity,Temperature\n"
        "2025-06-30T23:00:00,100,50.0,30.0,80,25.0\n"
        "2025-07-01T00:00,101,51.0,31.0,81,25.5\n"
    )
    df = load_raw_dataset(p)
    assert df["time"].tolist() == [pd.Timestamp("2025-06-30 23:00"), pd.Timestamp("2025-07-01 00:00")]
    assert df["time"].dt.tz is None


def test_bad_header_rejected(tmp_path):
    p = tmp_path / "d.csv"
    p.write_text("time,AQI\n2025-01-01T00:00:00,1\n")
    with pytest.raises(ValueError):
        load_raw_dataset(p)


def test_real_dataset_shape_and_hash():
    df = load_raw_dataset(config.DATA_PATH)
    assert len(df) == 41112
    assert df["time"].min() == pd.Timestamp("2022-01-13 00:00")
    assert df["time"].max() == pd.Timestamp("2026-09-22 23:00")
    assert not df["time"].duplicated().any()
    assert verify_dataset_hash() == compute_file_sha256()
