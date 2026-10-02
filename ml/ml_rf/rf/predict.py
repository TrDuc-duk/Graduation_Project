"""Suy luận Random Forest: lịch sử đến t -> AQI dự báo tại t+h.

Dùng lại build_inference_features của ml_xgb (cùng feature, cùng kiểm tra lịch sử/độ mới).

    python -m rf.predict
    python -m rf.predict --t "2026-09-20 12:00"
"""
import argparse
import re
from pathlib import Path

import pandas as pd

from rf import config
from rf.train import load_model_and_metadata
from src.data_loading import load_raw_dataset
from src.predict import OUTPUT_COLUMNS, InferenceDataError, build_inference_features  # noqa: F401


def available_horizons(models_dir: Path = config.MODELS_DIR) -> list[int]:
    return sorted(int(m.group(1)) for p in Path(models_dir).glob("rf_AQI_h*.joblib")
                  if (m := re.fullmatch(r"rf_AQI_h(\d+)\.joblib", p.name)))


def predict(history: pd.DataFrame, horizons: list[int] | None = None, t: pd.Timestamp | None = None,
            now: pd.Timestamp | None = None, node_id: str | None = None,
            models_dir: Path = config.MODELS_DIR) -> pd.DataFrame:
    horizons = horizons or available_horizons(models_dir)
    if not horizons:
        raise FileNotFoundError(f"Không có model trong {models_dir}")
    rows, feats = [], None
    for h in horizons:
        model, meta = load_model_and_metadata(h, models_dir)
        if feats is None:  # mọi model RF dùng cùng một bộ feature
            feats = build_inference_features(history, meta, t, now)
        input_time = feats["time"].iloc[0]
        pred = float(model.predict(feats[meta["feature_columns"]])[0])
        rows.append({"input_time": input_time, "target_time": input_time + pd.Timedelta(hours=h),
                     "horizon_hours": h, "predicted_aqi": pred, "model_version": meta["model_version"]})
    out = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if node_id is not None:
        out.insert(0, "node_id", node_id)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Dự báo AQI bằng Random Forest")
    ap.add_argument("--csv", type=Path, default=None)
    ap.add_argument("--t", default=None)
    ap.add_argument("--models-dir", type=Path, default=config.MODELS_DIR)
    args = ap.parse_args(argv)
    history = load_raw_dataset(args.csv) if args.csv else load_raw_dataset()
    out = predict(history, t=pd.Timestamp(args.t) if args.t else None, models_dir=args.models_dir)
    print(out.round({"predicted_aqi": 1}).to_string(index=False))


if __name__ == "__main__":
    main()
