"""Chọn tham số Random Forest bằng validation (grid search, không dùng test).

Tiêu chí: RMSE validation trung bình trên các horizon đại diện (config.TUNE_HORIZONS).
Ghi kèm train MAE để thấy mức overfit của từng bộ tham số.

    python -m rf.tune
"""
import argparse
import itertools
import json

import pandas as pd

from rf import config
from rf.train import train_one_horizon
from src.feature_engineering import get_feature_columns
from src.train import build_dataset


def grid(param_grid: dict) -> list[dict]:
    keys = list(param_grid)
    return [dict(zip(keys, vals)) for vals in itertools.product(*param_grid.values())]


def run_grid(horizons=config.TUNE_HORIZONS, param_grid=config.PARAM_GRID,
             n_estimators: int = config.TUNE_N_ESTIMATORS, data_bundle=None) -> pd.DataFrame:
    data, aqi_grid, _ = data_bundle or build_dataset(config.NAN_POLICY, config.HORIZONS)
    cols = get_feature_columns(config.NAN_POLICY)
    rows = []
    for i, p in enumerate(grid(param_grid)):
        params = {**p, "n_estimators": n_estimators}
        for h in horizons:
            res = train_one_horizon(data, aqi_grid, h, cols, params)
            val = next(r for r in res["rows"] if r["segment"] == "val" and r["method"] == "random_forest")
            rows.append({**p, "horizon": h, "val_MAE": val["MAE"], "val_RMSE": val["RMSE"],
                         "train_MAE": res["train_metrics"]["MAE"], "fit_seconds": res["fit_seconds"]})
            print(f"[{i + 1}] {p} h={h:>2}: val MAE={val['MAE']:.3f} RMSE={val['RMSE']:.3f} "
                  f"train MAE={res['train_metrics']['MAE']:.2f} ({res['fit_seconds']:.0f}s)", flush=True)
    return pd.DataFrame(rows)


def select_best(results: pd.DataFrame, param_keys) -> tuple[dict, pd.DataFrame]:
    summary = (results.groupby(list(param_keys))
               .agg(mean_val_RMSE=("val_RMSE", "mean"), mean_val_MAE=("val_MAE", "mean"),
                    mean_train_MAE=("train_MAE", "mean"))
               .sort_values("mean_val_RMSE").reset_index())
    best = summary.iloc[0][list(param_keys)].to_dict()
    best = {k: (int(v) if float(v).is_integer() and k != "max_features" else float(v)) for k, v in best.items()}
    return best, summary


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizons", nargs="+", type=int, default=config.TUNE_HORIZONS)
    args = ap.parse_args(argv)
    results = run_grid(args.horizons)
    best, summary = select_best(results, config.PARAM_GRID.keys())
    out = config.MODELS_DIR / "tuning"
    out.mkdir(parents=True, exist_ok=True)
    results.to_csv(out / "grid_results.csv", index=False)
    summary.to_csv(out / "grid_summary.csv", index=False)
    (out / "best_params.json").write_text(json.dumps(
        {"params": best, "criterion": "mean val RMSE over " + str(args.horizons),
         "mean_val_RMSE": float(summary.iloc[0]["mean_val_RMSE"])}, indent=2))
    print("\n" + summary.round(3).to_string(index=False))
    print(f"\nbest: {best} -> {out / 'best_params.json'}")


if __name__ == "__main__":
    main()
