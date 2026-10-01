"""Tối ưu cấu hình cho một horizon bằng validation (không đụng test).

    python -m src.tune --horizon 3 --trials 60
"""
import argparse
import json

import optuna

from src import config
from src.feature_engineering import get_feature_columns
from src.train import build_dataset, train_one_horizon

optuna.logging.set_verbosity(optuna.logging.WARNING)


def _val(res: dict, method: str = "xgboost") -> dict:
    return next(r for r in res["rows"] if r["segment"] == "val" and r["method"] == method)


def compare_policies(h: int, params: dict | None = None) -> dict:
    """So sánh chính sách NaN với tham số mặc định, chọn bằng validation."""
    out = {}
    for policy in ("no_fill", "ffill3h", "xgb_native_nan"):
        data, aqi, _ = build_dataset(policy, [h])
        cols = get_feature_columns(policy)
        res = train_one_horizon(data, aqi, h, cols, params=params)
        m = _val(res)
        out[policy] = {"MAE": m["MAE"], "RMSE": m["RMSE"], "n": m["n"], "n_trees": res["n_trees"]}
        print(f"{policy:>15}: MAE={m['MAE']:.3f} RMSE={m['RMSE']:.3f} n={m['n']} trees={res['n_trees']}", flush=True)
    return out


def tune(h: int, policy: str, trials: int, metric: str = "RMSE") -> tuple[dict, optuna.Study]:
    data, aqi, _ = build_dataset(policy, [h])
    cols = get_feature_columns(policy)

    def objective(trial: optuna.Trial) -> float:
        params = {
            **config.XGB_PARAMS,
            "n_estimators": 2000,
            "max_depth": trial.suggest_int("max_depth", 3, 9),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.1, log=True),
            "subsample": trial.suggest_float("subsample", 0.5, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.3, 1.0),
            "min_child_weight": trial.suggest_float("min_child_weight", 1, 50, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1e-2, 50, log=True),
            "reg_alpha": trial.suggest_float("reg_alpha", 1e-3, 10, log=True),
            "gamma": trial.suggest_float("gamma", 1e-3, 5, log=True),
        }
        res = train_one_horizon(data, aqi, h, cols, params=params)
        trial.set_user_attr("n_trees", res["n_trees"])
        return _val(res)[metric]

    study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=config.SEED))
    study.optimize(objective, n_trials=trials, show_progress_bar=False,
                   callbacks=[lambda s, t: print(f"trial {t.number:>3}: {metric}={t.value:.3f}  best={s.best_value:.3f}", flush=True)])
    best = {**config.XGB_PARAMS, "n_estimators": 2000, **study.best_params}
    return best, study


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=3)
    ap.add_argument("--policy", default=None, choices=["no_fill", "ffill3h", "xgb_native_nan"])
    ap.add_argument("--trials", type=int, default=60)
    ap.add_argument("--compare-only", action="store_true")
    args = ap.parse_args(argv)

    policy = args.policy
    if policy is None:
        print(f"== So sánh chính sách NaN (h={args.horizon}, tham số mặc định) ==")
        cmp = compare_policies(args.horizon)
        policy = min(cmp, key=lambda p: cmp[p]["RMSE"])
        print(f"-> chọn: {policy}")
    if args.compare_only:
        return
    print(f"\n== Optuna h={args.horizon}, policy={policy}, {args.trials} trials ==")
    best, study = tune(args.horizon, policy, args.trials)
    out = config.MODELS_DIR / "tuning"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"best_params_h{args.horizon}.json"
    path.write_text(json.dumps({"policy": policy, "val_RMSE": study.best_value, "params": best,
                                "n_trees": study.best_trial.user_attrs["n_trees"]}, indent=2))
    print(f"\nbest val RMSE={study.best_value:.3f}\n{json.dumps(best, indent=2)}\n-> {path}")


if __name__ == "__main__":
    main()
