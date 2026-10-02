"""Metric, bảng kết quả và biểu đồ."""
import numpy as np
import pandas as pd


def compute_metrics(y_true, y_pred) -> dict:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    ok = ~(np.isnan(y_true) | np.isnan(y_pred))
    if not ok.any():
        return {"n": 0, "MAE": np.nan, "RMSE": np.nan, "MAPE": np.nan}
    err = y_pred[ok] - y_true[ok]
    pos = ok & (y_true > 0)
    return {
        "n": int(ok.sum()),
        "MAE": float(np.mean(np.abs(err))),
        "RMSE": float(np.sqrt(np.mean(err**2))),
        "MAPE": float(np.mean(np.abs(y_pred[pos] - y_true[pos]) / y_true[pos]) * 100) if pos.any() else np.nan,
    }


def results_table(rows: list[dict]) -> pd.DataFrame:
    """rows: mỗi phần tử {horizon, segment, method, n, MAE, RMSE, MAPE}."""
    return pd.DataFrame(rows).sort_values(["segment", "horizon", "method"]).reset_index(drop=True)


def summarize(table: pd.DataFrame, segment: str, metric: str = "MAE", model: str = "xgboost") -> pd.DataFrame:
    """Bảng pivot horizon x method cho một segment, kèm mức cải thiện của `model` so với baseline."""
    t = table[table["segment"] == segment].pivot(index="horizon", columns="method", values=metric)
    if "persistence" in t and model in t:
        t["gain_vs_persistence_%"] = (1 - t[model] / t["persistence"]) * 100
        # persistence tốt theo chu kỳ 24h, nên so thêm với baseline tốt nhất ở từng horizon
        baselines = [c for c in ("persistence", "mean_24h", "same_hour_of_day") if c in t]
        t["best_baseline"] = t[baselines].min(axis=1)
        t["gain_vs_best_baseline_%"] = (1 - t[model] / t["best_baseline"]) * 100
    return t


# ---------------------------------------------------------------------------
# Đánh giá đầy đủ từ model đã lưu: bảng theo horizon/nguồn/mùa và biểu đồ.
# ---------------------------------------------------------------------------
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

COLORS = {"xgboost": "#2a78d6", "persistence": "#eb6834", "mean_24h": "#1baf7a",
          "same_hour_of_day": "#eda100"}
LABELS = {"xgboost": "XGBoost", "persistence": "Persistence", "mean_24h": "Trung bình 24h",
          "same_hour_of_day": "Cùng giờ gần nhất"}
INK, INK_MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
SEASONS = {12: "Đông (12-2)", 1: "Đông (12-2)", 2: "Đông (12-2)", 3: "Xuân (3-5)", 4: "Xuân (3-5)",
           5: "Xuân (3-5)", 6: "Hè (6-8)", 7: "Hè (6-8)", 8: "Hè (6-8)", 9: "Thu (9-11)",
           10: "Thu (9-11)", 11: "Thu (9-11)"}


def _style(ax, title, xlabel, ylabel):
    ax.set_title(title, loc="left", fontsize=11, color=INK)
    ax.set_xlabel(xlabel, color=INK_MUTED)
    ax.set_ylabel(ylabel, color=INK_MUTED)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=INK_MUTED)


def plot_error_by_horizon(table: pd.DataFrame, segment: str, out_path) -> None:
    t = table[table["segment"] == segment]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    for ax, metric in zip(axes, ("MAE", "RMSE")):
        piv = t.pivot(index="horizon", columns="method", values=metric)
        for m in COLORS:
            if m in piv:
                ax.plot(piv.index, piv[m], color=COLORS[m], linewidth=2, marker="o", markersize=4,
                        label=LABELS[m])
        if "xgboost" in piv:  # chỉ gắn nhãn trực tiếp cho model; baseline đọc qua legend
            ax.annotate(LABELS["xgboost"], (piv.index[-1], piv["xgboost"].iloc[-1]), xytext=(6, 0),
                        textcoords="offset points", va="center", fontsize=8, color=INK_MUTED)
        ax.set_xticks(piv.index[::2])
        ax.set_ylim(bottom=0)
        ax.set_xlim(right=piv.index.max() + 9)
        _style(ax, f"{metric} theo horizon ({segment})", "Horizon (giờ)", f"{metric} (điểm AQI)")
    axes[0].legend(frameon=False, fontsize=8, loc="lower right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_predicted_vs_actual(df: pd.DataFrame, h: int, segment: str, out_path, days: int = 14) -> None:
    """df: target_time, actual, xgboost. Trái: chuỗi thời gian `days` ngày cuối; phải: scatter."""
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 4.2), gridspec_kw={"width_ratios": [2.2, 1]})
    tail = df[df["target_time"] >= df["target_time"].max() - pd.Timedelta(days=days)]
    a1.plot(tail["target_time"], tail["actual"], color=INK, linewidth=1.5, label="AQI thực tế")
    a1.plot(tail["target_time"], tail["xgboost"], color=COLORS["xgboost"], linewidth=2,
            label=f"XGBoost dự báo trước {h}h")
    a1.legend(frameon=False, fontsize=8, loc="upper left")
    _style(a1, f"Dự báo {h}h so với thực tế, {days} ngày cuối ({segment})", "Thời điểm đích", "AQI")
    a1.tick_params(axis="x", labelrotation=30)
    lim = (0, max(df["actual"].max(), df["xgboost"].max()) * 1.05)
    a2.scatter(df["actual"], df["xgboost"], s=8, alpha=0.25, color=COLORS["xgboost"], edgecolors="none")
    a2.plot(lim, lim, color=INK_MUTED, linewidth=1, linestyle="--")
    a2.set_xlim(lim)
    a2.set_ylim(lim)
    m = compute_metrics(df["actual"], df["xgboost"])
    a2.text(0.04, 0.96, f"MAE {m['MAE']:.1f}\nRMSE {m['RMSE']:.1f}\nn = {m['n']}", transform=a2.transAxes,
            va="top", fontsize=8, color=INK_MUTED)
    _style(a2, "Dự báo vs thực tế", "AQI thực tế", "AQI dự báo")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_breakdown(bd: pd.DataFrame, segment: str, out_path, horizons=(3, 24, 72)) -> None:
    """MAE theo mùa: XGBoost vs persistence, mỗi horizon một panel."""
    d = bd[(bd["segment"] == segment) & (bd["group_type"] == "season") & bd["horizon"].isin(horizons)]
    if d.empty:
        return
    fig, axes = plt.subplots(1, len(horizons), figsize=(4.2 * len(horizons), 3.8), sharey=True)
    for ax, h in zip(np.atleast_1d(axes), horizons):
        x = d[d["horizon"] == h].set_index("group")
        groups = [g for g in dict.fromkeys(SEASONS.values()) if g in x.index]
        pos = np.arange(len(groups))
        for i, mth in enumerate(("xgboost", "persistence")):
            ax.bar(pos + (i - 0.5) * 0.38, x.loc[groups, f"MAE_{mth}"], width=0.36,
                   color=COLORS[mth], label=LABELS[mth], edgecolor="white", linewidth=1)
        ax.set_xticks(pos, groups, fontsize=8)
        _style(ax, f"h = {h}h", "", "MAE (điểm AQI)" if h == horizons[0] else "")
    np.atleast_1d(axes)[0].legend(frameon=False, fontsize=8, loc="upper left")
    fig.suptitle(f"MAE theo mùa ({segment})", x=0.01, ha="left", fontsize=11, color=INK)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def run_full_evaluation(models_dir=None, segments=("val", "test"), plot_horizons=(3, 24, 72)) -> pd.DataFrame:
    from src import config
    from src.baselines import evaluate_baselines
    from src.predict import available_horizons
    from src.split import select_valid_samples
    from src.targets import target_column
    from src.train import build_dataset, load_model_and_metadata, predict_with_model

    models_dir = models_dir or config.MODELS_DIR
    metrics_dir, plots_dir = models_dir / "metrics", models_dir / "plots"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)
    horizons = available_horizons(models_dir)
    datasets, rows, breakdown = {}, [], []
    for h in horizons:
        model, meta = load_model_and_metadata(h, models_dir)
        key = (meta["nan_policy"]["name"], meta.get("include_extra_features", False))
        if key not in datasets:
            datasets[key] = build_dataset(key[0], config.HORIZONS, include_extra=key[1])
        data, aqi_grid, _ = datasets[key]
        bounds = {k: pd.Timestamp(v) for k, v in meta["split_bounds"].items()}
        cols, tcol = meta["feature_columns"], target_column(h)
        for seg in segments:
            s, _ = select_valid_samples(data, h, seg, cols, bounds)
            if s.empty:
                continue
            preds = {"xgboost": predict_with_model(model, s[cols], meta["n_trees"]),
                     **evaluate_baselines(s, aqi_grid, h)}
            y = s[tcol].to_numpy()
            rows += [{"horizon": h, "segment": seg, "method": m, **compute_metrics(y, p)}
                     for m, p in preds.items()]
            target_time = s["time"] + pd.Timedelta(hours=h)
            groups = {"source": np.where(target_time < config.SOURCE_SWITCH, "legacy", "open_meteo"),
                      "season": target_time.dt.month.map(SEASONS).to_numpy()}
            for gtype, labels in groups.items():
                for g in pd.unique(labels):
                    mask = labels == g
                    mx = compute_metrics(y[mask], preds["xgboost"][mask])
                    mp = compute_metrics(y[mask], preds["persistence"][mask])
                    breakdown.append({"horizon": h, "segment": seg, "group_type": gtype, "group": g,
                                      "n": mx["n"], "MAE_xgboost": mx["MAE"], "MAE_persistence": mp["MAE"],
                                      "RMSE_xgboost": mx["RMSE"], "RMSE_persistence": mp["RMSE"]})
            if h in plot_horizons:
                df = pd.DataFrame({"target_time": target_time.to_numpy(), "actual": y,
                                   "xgboost": preds["xgboost"]})
                plot_predicted_vs_actual(df, h, seg, plots_dir / f"pred_vs_actual_h{h}_{seg}.png")
        print(f"đánh giá xong h={h}", flush=True)
    table = results_table(rows)
    bd = pd.DataFrame(breakdown)
    table.to_csv(metrics_dir / "evaluation_by_horizon.csv", index=False)
    bd.to_csv(metrics_dir / "evaluation_by_source_season.csv", index=False)
    for seg in table["segment"].unique():
        plot_error_by_horizon(table, seg, plots_dir / f"error_by_horizon_{seg}.png")
        plot_breakdown(bd, seg, plots_dir / f"mae_by_season_{seg}.png")
        summarize(table, seg, "MAE").to_csv(metrics_dir / f"summary_MAE_{seg}.csv")
        summarize(table, seg, "RMSE").to_csv(metrics_dir / f"summary_RMSE_{seg}.csv")
    return table


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    ap = argparse.ArgumentParser(description="Đánh giá model đã lưu, xuất bảng và biểu đồ")
    ap.add_argument("--models-dir", type=Path, default=None)
    ap.add_argument("--segments", nargs="+", default=["val", "test"])
    a = ap.parse_args()
    t = run_full_evaluation(a.models_dir, tuple(a.segments))
    for seg in t["segment"].unique():
        print(f"\n== MAE ({seg}) ==\n{summarize(t, seg, 'MAE').round(2).to_string()}")
