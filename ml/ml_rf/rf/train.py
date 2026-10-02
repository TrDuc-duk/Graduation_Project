"""Huấn luyện Random Forest: một RandomForestRegressor cho mỗi horizon (direct multi-step).

RF không có early stopping: tham số được chọn bằng validation (rf/tune.py). Test chỉ được
đánh giá khi --eval-test, sau khi đã chốt tham số.

    python -m rf.train --horizons 3            # chỉ validation
    python -m rf.train --horizons all --eval-test
"""
import argparse
import json
import platform
import time
from importlib import metadata as importlib_metadata
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor

from rf import config
from src.baselines import evaluate_baselines
from src.data_loading import verify_dataset_hash
from src.evaluate import compute_metrics, results_table, summarize
from src.feature_engineering import get_feature_columns
from src.split import DEFAULT_BOUNDS, count_samples_by_source, select_valid_samples
from src.targets import target_column
from src.train import AQI_DEFINITION, build_dataset, required_history_hours


def _segment_rows(model, samples, aqi_grid, h, cols, segment):
    """Metric của RF và các baseline trên cùng một tập mẫu."""
    y = samples[target_column(h)].to_numpy()
    preds = {"random_forest": model.predict(samples[cols])}
    preds.update(evaluate_baselines(samples, aqi_grid, h))
    return [{"horizon": h, "segment": segment, "method": m, **compute_metrics(y, p)}
            for m, p in preds.items()]


def train_one_horizon(data: pd.DataFrame, aqi_grid: np.ndarray, h: int, cols: list[str],
                      params: dict | None = None, bounds: dict | None = None,
                      evaluate_test: bool = False) -> dict:
    params = {**config.RF_PARAMS, **(params or {})}
    bounds = bounds or DEFAULT_BOUNDS
    tcol = target_column(h)
    train, log_tr = select_valid_samples(data, h, "train", cols, bounds)
    val, log_val = select_valid_samples(data, h, "val", cols, bounds)
    if len(train) == 0 or len(val) == 0:
        raise ValueError(f"h={h}: không có mẫu train/val hợp lệ")

    t0 = time.perf_counter()
    model = RandomForestRegressor(**params).fit(train[cols], train[tcol])
    fit_seconds = time.perf_counter() - t0

    train_metrics = compute_metrics(train[tcol], model.predict(train[cols]))
    rows = _segment_rows(model, val, aqi_grid, h, cols, "val")
    sample_counts = {"train": log_tr, "val": log_val,
                     "by_source": {"train": count_samples_by_source(train),
                                   "val": count_samples_by_source(val)}}
    if evaluate_test:
        test, log_te = select_valid_samples(data, h, "test", cols, bounds)
        rows += _segment_rows(model, test, aqi_grid, h, cols, "test")
        sample_counts["test"] = log_te
        sample_counts["by_source"]["test"] = count_samples_by_source(test)
    return {"model": model, "horizon": h, "params": params, "rows": rows,
            "train_metrics": train_metrics, "sample_counts": sample_counts,
            "fit_seconds": fit_seconds}


def library_versions() -> dict:
    out = {"python": platform.python_version()}
    for pkg in ("scikit-learn", "pandas", "numpy", "joblib"):
        out[pkg] = importlib_metadata.version(pkg)
    return out


def build_metadata(result: dict, cols: list[str], dataset_sha256: str | None, bounds: dict) -> dict:
    """Cùng các khóa với metadata XGBoost để dùng lại src.predict.build_inference_features."""
    h = result["horizon"]
    return {
        "model_type": "RandomForestRegressor",
        "model_version": config.MODEL_VERSION,
        "horizon_hours": h,
        "t_definition": "timestamp giờ dữ liệu mới nhất đã hoàn tất, giờ địa phương UTC+7 (naive)",
        "target_time_definition": f"target_time = t + {h}h; nhãn = AQI quan sát gốc tại target_time",
        "feature_columns": cols,
        "nan_policy": {"name": config.NAN_POLICY},
        "include_extra_features": False,
        "future_time_features": False,
        "required_history_hours": required_history_hours(),
        "aqi_definition": AQI_DEFINITION,
        "dataset_sha256": dataset_sha256,
        "split_bounds": {k: str(v) for k, v in bounds.items()},
        "seed": config.SEED,
        "library_versions": library_versions(),
        "rf_params": result["params"],
        "fit_seconds": round(result["fit_seconds"], 1),
        "train_metrics": result["train_metrics"],
        "sample_counts": result["sample_counts"],
        "metrics": result["rows"],
    }


def model_path(h: int, out_dir: Path = config.MODELS_DIR) -> Path:
    return Path(out_dir) / f"rf_AQI_h{h}.joblib"


def meta_path(h: int, out_dir: Path = config.MODELS_DIR) -> Path:
    return Path(out_dir) / f"rf_AQI_h{h}.meta.json"


def save_model_and_metadata(model, metadata: dict, out_dir: Path = config.MODELS_DIR) -> None:
    h = metadata["horizon_hours"]
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    joblib.dump(model, model_path(h, out_dir), compress=3)
    meta_path(h, out_dir).write_text(json.dumps(metadata, indent=2, ensure_ascii=False, default=str))


def load_model_and_metadata(h: int, out_dir: Path = config.MODELS_DIR):
    return joblib.load(model_path(h, out_dir)), json.loads(meta_path(h, out_dir).read_text())


def verify_reload_consistency(model, metadata: dict, X_sample: pd.DataFrame,
                              out_dir: Path = config.MODELS_DIR) -> bool:
    reloaded, meta = load_model_and_metadata(metadata["horizon_hours"], out_dir)
    cols = meta["feature_columns"]
    return bool(np.allclose(model.predict(X_sample[cols]), reloaded.predict(X_sample[cols])))


def run_training_pipeline(horizons=config.HORIZONS, params: dict | None = None,
                          evaluate_test: bool = False, out_dir: Path = config.MODELS_DIR,
                          verify_hash: bool = True) -> pd.DataFrame:
    sha = verify_dataset_hash() if verify_hash else None
    data, aqi_grid, _ = build_dataset(config.NAN_POLICY, config.HORIZONS)
    cols = get_feature_columns(config.NAN_POLICY)
    all_rows = []
    for h in horizons:
        res = train_one_horizon(data, aqi_grid, h, cols, params, evaluate_test=evaluate_test)
        meta = build_metadata(res, cols, sha, DEFAULT_BOUNDS)
        save_model_and_metadata(res["model"], meta, out_dir)
        if not verify_reload_consistency(res["model"], meta, data.dropna(subset=cols).tail(300), out_dir):
            raise RuntimeError(f"h={h}: dự đoán sau khi tải lại model không khớp")
        all_rows += res["rows"]
        val = {r["method"]: r["MAE"] for r in res["rows"] if r["segment"] == "val"}
        size_mb = model_path(h, out_dir).stat().st_size / 1e6
        print(f"h={h:>2}  fit={res['fit_seconds']:.0f}s  file={size_mb:.0f}MB  "
              f"train MAE={res['train_metrics']['MAE']:.2f}  val MAE: "
              + "  ".join(f"{m}={v:.2f}" for m, v in val.items()), flush=True)
        del res
    table = results_table(all_rows)
    metrics_dir = Path(out_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(metrics_dir / "metrics_by_horizon.csv", index=False)
    return table


def main(argv=None):
    ap = argparse.ArgumentParser(description="Train Random Forest AQI theo horizon")
    ap.add_argument("--horizons", nargs="+", default=["all"], help="vd: 3 24 72, hoặc 'all'")
    ap.add_argument("--params", type=Path, default=None, help="JSON tham số (vd models/tuning/best_params.json)")
    ap.add_argument("--eval-test", action="store_true", help="đánh giá test (chỉ sau khi chốt tham số)")
    ap.add_argument("--out-dir", type=Path, default=config.MODELS_DIR)
    args = ap.parse_args(argv)
    horizons = config.HORIZONS if args.horizons == ["all"] else [int(x) for x in args.horizons]
    params = json.loads(args.params.read_text())["params"] if args.params else None
    table = run_training_pipeline(horizons, params, args.eval_test, args.out_dir)
    for seg in table["segment"].unique():
        for metric in ("MAE", "RMSE"):
            s = summarize(table, seg, metric, model="random_forest")
            print(f"\n== {metric} ({seg}) ==\n{s.round(2).to_string()}")


if __name__ == "__main__":
    main()
