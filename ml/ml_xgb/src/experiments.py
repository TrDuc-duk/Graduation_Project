"""Thí nghiệm tối ưu cho các horizon ngắn. Mọi cấu hình được so trên CÙNG tập validation;
test không được dùng ở đây. Kiểm tra overfit bằng: (1) chênh lệch train/val, (2) độ lệch
chuẩn qua nhiều seed, (3) walk-forward CV trong đoạn train+val.

    python -m src.experiments --horizons 3 6 9 12 --stage compare
"""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

from src import config
from src.baselines import persistence
from src.evaluate import compute_metrics
from src.feature_engineering import get_feature_columns
from src.split import DEFAULT_BOUNDS, select_valid_samples
from src.targets import target_column
from src.train import build_dataset

SEEDS = (42, 43, 44)
OUT_DIR = config.MODELS_DIR / "experiments"

CONFIGS = {
    "E0_baseline":       dict(extra=False, delta=False, keep_nan=False),
    "E1_delta_target":   dict(extra=False, delta=True,  keep_nan=False),
    "E2_extra_features": dict(extra=True,  delta=False, keep_nan=False),
    "E3_delta+extra":    dict(extra=True,  delta=True,  keep_nan=False),
    "E4_native_nan":     dict(extra=False, delta=False, keep_nan=True),
    "E5_delta+extra+nan": dict(extra=True, delta=True,  keep_nan=True),
}


def _fit_predict(train, val, cols, h, params, delta, seed, early_stopping_rounds):
    tcol = target_column(h)
    y_tr, y_val = train[tcol].to_numpy(), val[tcol].to_numpy()
    base_tr = train["AQI"].to_numpy() if delta else 0.0
    base_val = val["AQI"].to_numpy() if delta else 0.0
    model = xgb.XGBRegressor(**{**params, "random_state": seed,
                                "early_stopping_rounds": early_stopping_rounds})
    model.fit(train[cols], y_tr - base_tr, eval_set=[(val[cols], y_val - base_val)], verbose=False)
    n_trees = int(model.best_iteration) + 1
    pred = lambda df, base: model.predict(df[cols], iteration_range=(0, n_trees)) + base
    return {"n_trees": n_trees, "val_pred": pred(val, base_val), "train_pred": pred(train, base_tr)}


def run_config(data, h, cfg, params=None, bounds=None, seeds=SEEDS, val_index=None,
               early_stopping_rounds=config.EARLY_STOPPING_ROUNDS):
    """Train + đánh giá một cấu hình. data phải có sẵn cột extra nếu cfg['extra']."""
    params = {**config.XGB_PARAMS, **(params or {})}
    bounds = bounds or DEFAULT_BOUNDS
    cols = get_feature_columns(include_extra=cfg["extra"])
    complete = not cfg["keep_nan"]
    train, _ = select_valid_samples(data, h, "train", cols, bounds, require_complete_features=complete)
    val, _ = select_valid_samples(data, h, "val", cols, bounds, require_complete_features=complete)
    if cfg["delta"]:  # target dạng delta cần AQI tại t
        train, val = train[train["AQI"].notna()], val[val["AQI"].notna()]
    if val_index is not None:  # ép mọi cấu hình đánh giá trên cùng một tập val
        val = val.loc[val.index.intersection(val_index)]
        assert len(val) == len(val_index), "val không đồng nhất giữa các cấu hình"
    tcol = target_column(h)
    runs = [_fit_predict(train, val, cols, h, params, cfg["delta"], s, early_stopping_rounds) for s in seeds]
    val_m = [compute_metrics(val[tcol], r["val_pred"]) for r in runs]
    tr_m = [compute_metrics(train[tcol], r["train_pred"]) for r in runs]
    out = {
        "n_train": len(train), "n_val": len(val),
        "val_MAE": np.mean([m["MAE"] for m in val_m]), "val_RMSE": np.mean([m["RMSE"] for m in val_m]),
        "val_MAE_std": np.std([m["MAE"] for m in val_m]), "val_RMSE_std": np.std([m["RMSE"] for m in val_m]),
        "train_MAE": np.mean([m["MAE"] for m in tr_m]), "train_RMSE": np.mean([m["RMSE"] for m in tr_m]),
        "n_trees": float(np.mean([r["n_trees"] for r in runs])),
    }
    out["val_pred_mean"] = np.mean([r["val_pred"] for r in runs], axis=0)
    out["val"] = val
    return out


def common_val_index(data, h, bounds=None):
    """Tập val chung: mẫu có đủ feature (kể cả extra) và AQI tại t."""
    cols = get_feature_columns(include_extra=True)
    val, _ = select_valid_samples(data, h, "val", cols, bounds or DEFAULT_BOUNDS)
    return val[val["AQI"].notna()].index


def compare_configs(horizons, params=None, configs=CONFIGS) -> pd.DataFrame:
    data, _, _ = build_dataset(horizons=config.HORIZONS, include_extra=True)
    rows = []
    for h in horizons:
        idx = common_val_index(data, h)
        pers = compute_metrics(data.loc[idx, target_column(h)], persistence(data.loc[idx]))
        rows.append({"horizon": h, "config": "persistence", "n_val": len(idx),
                     "val_MAE": pers["MAE"], "val_RMSE": pers["RMSE"]})
        for name, cfg in configs.items():
            r = run_config(data, h, cfg, params, val_index=idx)
            rows.append({"horizon": h, "config": name, **{k: v for k, v in r.items()
                                                          if k not in ("val_pred_mean", "val")}})
            print(f"h={h:>2} {name:<20} val MAE={r['val_MAE']:.3f}±{r['val_MAE_std']:.3f} "
                  f"RMSE={r['val_RMSE']:.3f}±{r['val_RMSE_std']:.3f}  "
                  f"train MAE={r['train_MAE']:.2f}  trees={r['n_trees']:.0f}", flush=True)
    df = pd.DataFrame(rows)
    base = df[df["config"] == "E0_baseline"].set_index("horizon")
    for m in ("MAE", "RMSE"):
        df[f"{m}_gain_vs_E0_%"] = [(1 - r[f"val_{m}"] / base.loc[r["horizon"], f"val_{m}"]) * 100
                                    for _, r in df.iterrows()]
    return df


def walk_forward_bounds(times: pd.Series, cuts=(0.45, 0.55, 0.65, 0.75, 0.85)) -> list[dict]:
    """Các fold mở rộng dần, tất cả kết thúc trước VAL_END (không chạm test)."""
    t = pd.Series(times).reset_index(drop=True)
    pos = [t.iloc[int(np.floor(len(t) * c))] for c in cuts]
    assert pos[-1] <= config.VAL_END
    return [{"train_start": t.iloc[0], "train_end": pos[i], "val_end": pos[i + 1], "test_end": pos[i + 1]}
            for i in range(len(pos) - 1)]


def walk_forward(horizons, config_names, params=None, seeds=(42,)) -> pd.DataFrame:
    data, _, _ = build_dataset(horizons=config.HORIZONS, include_extra=True)
    folds = walk_forward_bounds(data["time"])
    rows = []
    for h in horizons:
        for k, b in enumerate(folds):
            idx = common_val_index(data, h, b)
            pers = compute_metrics(data.loc[idx, target_column(h)], persistence(data.loc[idx]))
            rows.append({"horizon": h, "fold": k, "config": "persistence", "fold_val_start": b["train_end"],
                         "val_MAE": pers["MAE"], "val_RMSE": pers["RMSE"]})
            for name in config_names:
                r = run_config(data, h, CONFIGS[name], params, bounds=b, seeds=seeds, val_index=idx)
                rows.append({"horizon": h, "fold": k, "config": name, "fold_val_start": b["train_end"],
                             "val_MAE": r["val_MAE"], "val_RMSE": r["val_RMSE"],
                             "train_MAE": r["train_MAE"], "n_trees": r["n_trees"]})
                print(f"h={h:>2} fold={k} ({b['train_end']:%Y-%m-%d}) {name:<20} "
                      f"MAE={r['val_MAE']:.3f} RMSE={r['val_RMSE']:.3f}", flush=True)
    return pd.DataFrame(rows)


def error_analysis(h: int, config_name: str, params=None) -> dict[str, pd.DataFrame]:
    """Phân tích sai số trên validation theo mức AQI, độ biến động, nguồn, giờ, tháng."""
    data, _, _ = build_dataset(horizons=config.HORIZONS, include_extra=True)
    idx = common_val_index(data, h)
    r = run_config(data, h, CONFIGS[config_name], params, val_index=idx)
    val = r["val"].copy()
    tcol = target_column(h)
    val["pred"] = r["val_pred_mean"]
    val["err"] = val["pred"] - val[tcol]
    val["abs_err"] = val["err"].abs()
    val["abs_err_persistence"] = (val["AQI"] - val[tcol]).abs()
    val["target_time"] = val["time"] + pd.Timedelta(hours=h)
    val["actual_change"] = (val[tcol] - val["AQI"]).abs()
    val["source"] = np.where(val["target_time"] < config.SOURCE_SWITCH, "legacy", "open_meteo")
    val["aqi_level"] = pd.cut(val[tcol], [0, 50, 100, 150, 200, 300, 501],
                              labels=["0-50", "51-100", "101-150", "151-200", "201-300", "301-500"])
    val["change_bin"] = pd.cut(val["actual_change"], [-0.1, 10, 25, 50, 100, 1000],
                               labels=["<=10", "10-25", "25-50", "50-100", ">100"])

    def grp(key):
        g = val.groupby(key, observed=True)
        out = g.agg(n=("abs_err", "size"), MAE=("abs_err", "mean"),
                    MAE_persistence=("abs_err_persistence", "mean"), bias=("err", "mean"))
        out["share_of_total_abs_err_%"] = g["abs_err"].sum() / val["abs_err"].sum() * 100
        return out.round(2)

    sq = np.sort(val["err"].to_numpy() ** 2)[::-1]
    concentration = pd.DataFrame({
        "top_%": [1, 5, 10],
        "share_of_squared_error_%": [sq[: max(1, int(len(sq) * p / 100))].sum() / sq.sum() * 100
                                     for p in (1, 5, 10)],
    }).round(1)
    top = val.sort_values("abs_err", ascending=False)
    return {
        "by_level": grp("aqi_level"), "by_change": grp("change_bin"), "by_source": grp("source"),
        "by_hour": grp(val["target_time"].dt.hour.rename("target_hour")),
        "by_month": grp(val["target_time"].dt.to_period("M").rename("target_month")),
        "concentration": concentration,
        "top_errors": top[["time", "target_time", "AQI", tcol, "pred", "err", "AQI_diff3",
                           "pm2_5", "pm10", "Humidity", "source"]].head(20).round(
            {"pred": 1, "err": 1, "pm2_5": 1, "pm10": 1}),
        "val": val,
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizons", nargs="+", type=int, default=[3, 6, 9, 12])
    ap.add_argument("--stage", default="compare", choices=["compare", "walkforward", "errors"])
    ap.add_argument("--configs", nargs="+", default=["E0_baseline", "E3_delta+extra"])
    ap.add_argument("--params", type=Path, default=None, help="JSON params (vd từ Optuna)")
    args = ap.parse_args(argv)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    params = json.loads(args.params.read_text())["params"] if args.params else None
    if args.stage == "compare":
        df = compare_configs(args.horizons, params)
        df.to_csv(OUT_DIR / "compare_configs.csv", index=False)
        show = df.drop(columns=[c for c in ("n_train", "val_MAE_std", "val_RMSE_std", "train_RMSE") if c in df])
        print("\n" + show.round(3).to_string(index=False))
    elif args.stage == "walkforward":
        df = walk_forward(args.horizons, args.configs, params)
        df.to_csv(OUT_DIR / "walk_forward.csv", index=False)
        piv = df.pivot_table(index=["horizon", "fold"], columns="config", values="val_MAE")
        for c in args.configs:
            if c != "E0_baseline" and "E0_baseline" in piv:
                piv[f"{c}_gain_%"] = (1 - piv[c] / piv["E0_baseline"]) * 100
        print("\n== walk-forward val MAE ==\n" + piv.round(3).to_string())
    else:
        for h in args.horizons:
            res = error_analysis(h, args.configs[-1], params)
            print(f"\n######## h={h}  config={args.configs[-1]} ########")
            for k, v in res.items():
                if k == "val":
                    v.to_csv(OUT_DIR / f"val_errors_h{h}.csv", index=False)
                    continue
                print(f"\n-- {k} --\n{v.to_string()}")


if __name__ == "__main__":
    main()
