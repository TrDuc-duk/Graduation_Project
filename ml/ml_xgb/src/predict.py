"""Suy luận: lịch sử đến t -> AQI dự báo tại t+h cho các horizon đã train.

Dùng đúng hàm tạo feature của lúc train, với cấu hình đọc từ metadata model.

    python -m src.predict                      # dùng dataset.csv, t = giờ mới nhất
    python -m src.predict --t "2026-09-20 12:00"
"""
import argparse
import re
from pathlib import Path

import pandas as pd

from src import config
from src.data_loading import load_raw_dataset
from src.feature_engineering import build_feature_matrix
from src.preprocessing import apply_nan_policy, build_hourly_grid
from src.train import load_model_and_metadata, predict_with_model

OUTPUT_COLUMNS = ["input_time", "target_time", "horizon_hours", "predicted_aqi", "model_version"]


class InferenceDataError(ValueError):
    """Dữ liệu đầu vào không đủ mới hoặc không đủ lịch sử để dự báo."""


def available_horizons(models_dir: Path = config.MODELS_DIR) -> list[int]:
    hs = [int(m.group(1)) for p in Path(models_dir).glob("xgb_AQI_h*.json")
          if (m := re.fullmatch(r"xgb_AQI_h(\d+)\.json", p.name))]
    return sorted(hs)


def build_inference_features(history: pd.DataFrame, meta: dict, t: pd.Timestamp | None = None,
                             now: pd.Timestamp | None = None,
                             max_staleness: pd.Timedelta = pd.Timedelta(hours=2)) -> pd.DataFrame:
    """Trả về một hàng feature tại t (giờ dữ liệu mới nhất đã hoàn tất).

    history: cột time + AQI, pm10, pm2_5, Humidity, Temperature (giờ địa phương, naive)."""
    hist = history[history["time"] <= t] if t is not None else history  # bỏ mọi dữ liệu sau t
    if hist.empty:
        raise InferenceDataError("Không có dữ liệu trước hoặc tại t")
    t = hist["time"].max() if t is None else pd.Timestamp(t)
    if not (hist["time"] == t).any():
        raise InferenceDataError(f"Không có quan sát tại t={t}")
    if now is not None and pd.Timestamp(now) - t > max_staleness:
        raise InferenceDataError(f"Dữ liệu cũ: t={t}, now={now}, quá {max_staleness}")
    need = meta["required_history_hours"]
    hist = hist[hist["time"] > t - pd.Timedelta(hours=need + 24)]  # đủ cửa sổ, tránh tính cả chuỗi
    grid, _ = apply_nan_policy(build_hourly_grid(hist), meta["nan_policy"]["name"])
    X = build_feature_matrix(grid, policy=meta["nan_policy"]["name"],
                             include_extra=meta.get("include_extra_features", False))
    row = X[X["time"] == t]
    cols = meta["feature_columns"]
    missing = [c for c in cols if row[c].isna().any()]
    if missing and meta["nan_policy"]["name"] != "xgb_native_nan":
        raise InferenceDataError(
            f"Thiếu lịch sử tại t={t}: cần {need} giờ liên tục; feature thiếu: {missing[:5]}...")
    return row[["time"] + cols]


def predict(history: pd.DataFrame, horizons: list[int] | None = None, t: pd.Timestamp | None = None,
            now: pd.Timestamp | None = None, node_id: str | None = None,
            models_dir: Path = config.MODELS_DIR) -> pd.DataFrame:
    horizons = horizons or available_horizons(models_dir)
    if not horizons:
        raise FileNotFoundError(f"Không có model trong {models_dir}")
    rows, cache = [], {}
    for h in horizons:
        model, meta = load_model_and_metadata(h, models_dir)
        key = (meta["nan_policy"]["name"], meta.get("include_extra_features", False),
               tuple(meta["feature_columns"]))
        if key not in cache:
            cache[key] = build_inference_features(history, meta, t, now)
        feats = cache[key]
        input_time = feats["time"].iloc[0]
        pred = float(predict_with_model(model, feats[meta["feature_columns"]], meta["n_trees"])[0])
        rows.append({"input_time": input_time, "target_time": input_time + pd.Timedelta(hours=h),
                     "horizon_hours": h, "predicted_aqi": pred, "model_version": meta["model_version"]})
    out = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if node_id is not None:
        out.insert(0, "node_id", node_id)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Dự báo AQI cho các horizon đã train")
    ap.add_argument("--csv", type=Path, default=config.DATA_PATH)
    ap.add_argument("--t", default=None, help="thời điểm đầu vào (mặc định: giờ mới nhất trong CSV)")
    ap.add_argument("--models-dir", type=Path, default=config.MODELS_DIR)
    args = ap.parse_args(argv)
    history = load_raw_dataset(args.csv)
    t = pd.Timestamp(args.t) if args.t else None
    out = predict(history, t=t, models_dir=args.models_dir)
    print(out.round({"predicted_aqi": 1}).to_string(index=False))


if __name__ == "__main__":
    main()
