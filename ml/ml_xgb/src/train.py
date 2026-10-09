"""Huấn luyện direct multi-step: một XGBRegressor cho mỗi horizon.

Quy trình (PLAN.md mục 8): train trên train, early stopping bằng val, dùng chính model đó để
đánh giá; refit train+val là tùy chọn. Test chỉ được tính khi evaluate_test=True.
"""
import argparse
import json
import platform
from importlib import metadata as importlib_metadata
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from src import config
from src.baselines import evaluate_baselines
from src.data_loading import load_raw_dataset, verify_dataset_hash
from src.evaluate import compute_metrics, results_table, summarize
from src.feature_engineering import build_feature_matrix, get_feature_columns
from src.preprocessing import build_hourly_grid, prepare_grid
from src.split import DEFAULT_BOUNDS, count_samples_by_source, legacy_only_bounds, select_valid_samples
from src.targets import add_targets, target_column

AQI_DEFINITION = (
    "Bảng 3.3/3.4 báo cáo; tính từ PM từng dòng (không trung bình 24h/NowCast); cắt PM2.5 1 chữ số, "
    "PM10 nguyên; nội suy; làm tròn .5 lên; vượt bảng -> 500; max(PM2.5, PM10)"
)
PREDICT_API = "XGBRegressor.predict(iteration_range=(0, n_trees))"


def build_dataset(nan_policy: str = config.NAN_POLICY, horizons=config.HORIZONS,
                  path: Path = config.DATA_PATH, raw: pd.DataFrame | None = None,
                  include_extra: bool = False):
    """Trả về (data = features + target_*, aqi_grid (AQI đầu vào theo lưới), policy_meta)."""
    raw = load_raw_dataset(path) if raw is None else raw
    grid, policy_meta = prepare_grid(raw, nan_policy)
    X = build_feature_matrix(grid, policy=nan_policy, include_extra=include_extra)
    targets = add_targets(grid, horizons)[[target_column(h) for h in horizons]]
    data = pd.concat([X, targets], axis=1)
    return data, grid["AQI"].to_numpy(dtype=float), policy_meta


def predict_with_model(model: xgb.XGBRegressor, X: pd.DataFrame, n_trees: int) -> np.ndarray:
    return model.predict(X, iteration_range=(0, n_trees))


def _fit(params: dict, X_tr, y_tr, X_val=None, y_val=None, early_stopping_rounds=None):
    p = dict(params)
    if early_stopping_rounds:
        p["early_stopping_rounds"] = early_stopping_rounds
    model = xgb.XGBRegressor(**p)
    if X_val is not None:
        model.fit(X_tr, y_tr, eval_set=[(X_val, y_val)], verbose=False)
    else:
        model.fit(X_tr, y_tr, verbose=False)
    return model


def _segment_rows(model, samples, aqi_grid, h, cols, n_trees, segment):
    """Metric của model và các baseline trên cùng một tập mẫu."""
    y = samples[target_column(h)].to_numpy()
    preds = {"xgboost": predict_with_model(model, samples[cols], n_trees)}
    preds.update(evaluate_baselines(samples, aqi_grid, h))
    return [{"horizon": h, "segment": segment, "method": m, **compute_metrics(y, p)}
            for m, p in preds.items()], preds


def train_one_horizon(data: pd.DataFrame, aqi_grid: np.ndarray, h: int, cols: list[str],
                      params: dict | None = None, bounds: dict | None = None,
                      early_stopping_rounds: int = config.EARLY_STOPPING_ROUNDS,
                      refit: bool = False, evaluate_test: bool = False, native_nan: bool = False):
    """native_nan=True: giữ hàng train thiếu feature cho XGBoost tự xử lý. Val/test luôn dùng
    mẫu đủ feature để model và baseline được so trên cùng một tập."""
    params = dict(config.XGB_PARAMS if params is None else params)
    bounds = bounds or DEFAULT_BOUNDS
    tcol = target_column(h)
    train, log_tr = select_valid_samples(data, h, "train", cols, bounds,
                                         require_complete_features=not native_nan)
    val, log_val = select_valid_samples(data, h, "val", cols, bounds)
    if len(train) == 0 or len(val) == 0:
        raise ValueError(f"h={h}: không có mẫu train/val hợp lệ")

    model = _fit(params, train[cols], train[tcol], val[cols], val[tcol], early_stopping_rounds)
    best_iteration = int(model.best_iteration)
    n_trees = best_iteration + 1
    best_score = float(model.best_score)

    if refit:
        merged_bounds = {**bounds, "train_end": bounds["val_end"]}
        trainval, log_trval = select_valid_samples(data, h, "train", cols, merged_bounds,
                                                   require_complete_features=not native_nan)
        refit_params = {**params, "n_estimators": n_trees}
        model = _fit(refit_params, trainval[cols], trainval[tcol])

    rows, _ = _segment_rows(model, val, aqi_grid, h, cols, n_trees, "val")
    sample_counts = {"train": log_tr, "val": log_val,
                     "by_source": {"train": count_samples_by_source(train),
                                   "val": count_samples_by_source(val)}}
    if refit:
        sample_counts["refit_train_val"] = log_trval
    test_rows = []
    if evaluate_test:
        test, log_te = select_valid_samples(data, h, "test", cols, bounds)
        test_rows, _ = _segment_rows(model, test, aqi_grid, h, cols, n_trees, "test")
        sample_counts["test"] = log_te
        sample_counts["by_source"]["test"] = count_samples_by_source(test)
    rows += test_rows
    return {
        "model": model, "horizon": h, "n_trees": n_trees, "best_iteration": best_iteration,
        "best_score": best_score, "rows": rows, "sample_counts": sample_counts, "refit": refit,
        "params": params,
    }


def library_versions() -> dict:
    out = {"python": platform.python_version()}
    for pkg in ("xgboost", "pandas", "numpy", "scikit-learn"):
        out[pkg] = importlib_metadata.version(pkg)
    return out


def required_history_hours() -> int:
    """Số giờ lịch sử liên tục (tính cả t) cần để mọi lag/rolling tại t có giá trị."""
    return max(max(config.LAG_HOURS), max(config.ROLLING_WINDOWS) - 1) + 1


def build_metadata(result: dict, cols: list[str], policy_meta: dict, dataset_sha256: str,
                   bounds: dict, include_extra: bool = False) -> dict:
    h = result["horizon"]
    return {
        "model_version": config.MODEL_VERSION,
        "horizon_hours": h,
        "t_definition": "timestamp giờ dữ liệu mới nhất đã hoàn tất, giờ địa phương UTC+7 (naive)",
        "target_time_definition": f"target_time = t + {h}h; nhãn = AQI quan sát gốc tại target_time",
        "feature_columns": cols,
        "nan_policy": policy_meta,
        "lag_hours": config.LAG_HOURS,
        "rolling": {"windows": config.ROLLING_WINDOWS, "stats": config.ROLLING_STATS,
                    "min_periods": "bằng kích thước cửa sổ", "window_end": "t"},
        "future_time_features": False,
        "include_extra_features": include_extra,
        "required_history_hours": required_history_hours(),
        "aqi_definition": AQI_DEFINITION,
        "dataset_sha256": dataset_sha256,
        "split_bounds": {k: str(v) for k, v in bounds.items()},
        "seed": config.SEED,
        "library_versions": library_versions(),
        "xgb_params": {k: v for k, v in result["params"].items()},
        "early_stopping_rounds": config.EARLY_STOPPING_ROUNDS,
        "early_stopping_metric": result["params"].get("eval_metric", "rmse"),
        "best_iteration": result["best_iteration"],
        "best_validation_score": result["best_score"],
        "n_trees": result["n_trees"],
        "predict_api": PREDICT_API,
        "refit_on_train_val": result["refit"],
        "sample_counts": result["sample_counts"],
        "metrics": result["rows"],
    }


def model_path(h: int, out_dir: Path = config.MODELS_DIR) -> Path:
    return Path(out_dir) / f"xgb_AQI_h{h}.json"


def meta_path(h: int, out_dir: Path = config.MODELS_DIR) -> Path:
    return Path(out_dir) / f"xgb_AQI_h{h}.meta.json"


def save_model_and_metadata(model: xgb.XGBRegressor, metadata: dict, out_dir: Path = config.MODELS_DIR) -> None:
    h = metadata["horizon_hours"]
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    model.save_model(model_path(h, out_dir))
    meta_path(h, out_dir).write_text(json.dumps(metadata, indent=2, ensure_ascii=False, default=str))


def load_model_and_metadata(h: int, out_dir: Path = config.MODELS_DIR):
    model = xgb.XGBRegressor()
    model.load_model(model_path(h, out_dir))
    meta = json.loads(meta_path(h, out_dir).read_text())
    return model, meta


def verify_reload_consistency(model, metadata: dict, X_sample: pd.DataFrame, out_dir: Path = config.MODELS_DIR) -> bool:
    reloaded, meta = load_model_and_metadata(metadata["horizon_hours"], out_dir)
    a = predict_with_model(model, X_sample[metadata["feature_columns"]], metadata["n_trees"])
    b = predict_with_model(reloaded, X_sample[meta["feature_columns"]], meta["n_trees"])
    return bool(np.allclose(a, b))


def run_training_pipeline(horizons=config.HORIZONS, nan_policy: str = config.NAN_POLICY,
                          refit: bool = False, evaluate_test: bool = False,
                          out_dir: Path = config.MODELS_DIR, verify_hash: bool = True,
                          bounds: dict | None = None, tag: str = "") -> pd.DataFrame:
    sha = verify_dataset_hash() if verify_hash else None
    bounds = bounds or DEFAULT_BOUNDS
    data, aqi_grid, policy_meta = build_dataset(nan_policy, horizons)
    cols = get_feature_columns(nan_policy)
    all_rows = []
    for h in horizons:
        res = train_one_horizon(data, aqi_grid, h, cols, bounds=bounds, refit=refit,
                                evaluate_test=evaluate_test, native_nan=nan_policy == "xgb_native_nan")
        meta = build_metadata(res, cols, policy_meta, sha, bounds)
        save_model_and_metadata(res["model"], meta, out_dir)
        sample = data.dropna(subset=cols).tail(500)
        if not verify_reload_consistency(res["model"], meta, sample, out_dir):
            raise RuntimeError(f"h={h}: dự đoán sau khi tải lại model không khớp")
        all_rows += res["rows"]
        val = {r["method"]: r["MAE"] for r in res["rows"] if r["segment"] == "val"}
        print(f"h={h:>2}  trees={res['n_trees']:>4}  val MAE: " +
              "  ".join(f"{m}={v:.2f}" for m, v in val.items()), flush=True)
    table = results_table(all_rows)
    metrics_dir = Path(out_dir) / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(metrics_dir / f"metrics_by_horizon{tag}.csv", index=False)
    return table


def main(argv=None):
    ap = argparse.ArgumentParser(description="Train XGBoost AQI theo horizon")
    ap.add_argument("--horizons", nargs="+", default=["all"], help="vd: 3 24 72, hoặc 'all'")
    ap.add_argument("--policy", default=config.NAN_POLICY, choices=["no_fill", "ffill3h", "xgb_native_nan"])
    ap.add_argument("--refit", action="store_true", help="refit trên train+val sau khi chọn n_trees")
    ap.add_argument("--eval-test", action="store_true", help="đánh giá test (chỉ sau khi chốt cấu hình)")
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--legacy-only", action="store_true",
                    help="split 70/15/15 riêng trong đoạn nguồn cũ (trước 07/2025); lưu vào models/legacy_only")
    args = ap.parse_args(argv)
    horizons = config.HORIZONS if args.horizons == ["all"] else [int(x) for x in args.horizons]
    bounds, out_dir = None, args.out_dir or config.MODELS_DIR
    if args.legacy_only:
        raw = load_raw_dataset()
        bounds = legacy_only_bounds(build_hourly_grid(raw)["time"])
        out_dir = args.out_dir or config.LEGACY_MODELS_DIR
    table = run_training_pipeline(horizons, args.policy, args.refit, args.eval_test, out_dir, bounds=bounds)
    for seg in table["segment"].unique():
        print(f"\n== MAE ({seg}) ==")
        print(summarize(table, seg, "MAE").round(2).to_string())
        print(f"\n== RMSE ({seg}) ==")
        print(summarize(table, seg, "RMSE").round(2).to_string())


if __name__ == "__main__":
    main()
