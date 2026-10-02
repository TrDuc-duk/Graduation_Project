"""So sánh Random Forest với XGBoost và baseline trên cùng tập mẫu (đọc metric đã lưu).

    python -m rf.compare            # -> models/comparison/*.csv, *.png
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from rf import config  # noqa: E402
from src import config as xgb_config  # noqa: E402
from src.evaluate import COLORS, LABELS, _style  # noqa: E402

RF_COLOR = "#e87ba4"  # slot 5 của palette; các thực thể khác giữ nguyên màu như biểu đồ XGBoost
BASELINES = ("persistence", "mean_24h", "same_hour_of_day")


def load_tables() -> pd.DataFrame:
    rf = pd.read_csv(config.MODELS_DIR / "metrics" / "metrics_by_horizon.csv")
    xgb = pd.read_csv(xgb_config.MODELS_DIR / "metrics" / "metrics_by_horizon.csv")
    xgb = xgb[xgb["method"] == "xgboost"]
    both = pd.concat([rf, xgb], ignore_index=True)
    # Hai model phải được đánh giá trên cùng tập mẫu thì mới so được
    n = both.pivot_table(index=["segment", "horizon"], columns="method", values="n")
    if not (n.nunique(axis=1) == 1).all():
        raise ValueError("Số mẫu RF và XGBoost khác nhau: không cùng tập đánh giá")
    return both


def comparison(both: pd.DataFrame, segment: str, metric: str) -> pd.DataFrame:
    t = both[both["segment"] == segment].pivot(index="horizon", columns="method", values=metric)
    t["best_baseline"] = t[list(BASELINES)].min(axis=1)
    t["rf_vs_xgb_%"] = (1 - t["random_forest"] / t["xgboost"]) * 100
    t["rf_vs_best_baseline_%"] = (1 - t["random_forest"] / t["best_baseline"]) * 100
    t["xgb_vs_best_baseline_%"] = (1 - t["xgboost"] / t["best_baseline"]) * 100
    return t[["random_forest", "xgboost", "best_baseline", "rf_vs_xgb_%",
              "rf_vs_best_baseline_%", "xgb_vs_best_baseline_%"]]


def plot(both: pd.DataFrame, segment: str, out_path) -> None:
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2))
    for ax, metric in zip(axes, ("MAE", "RMSE")):
        t = both[both["segment"] == segment].pivot(index="horizon", columns="method", values=metric)
        best = t[list(BASELINES)].min(axis=1)
        ax.plot(t.index, best, color="#8f8e88", linewidth=1.5, linestyle="--", label="Baseline tốt nhất")
        ax.plot(t.index, t["xgboost"], color=COLORS["xgboost"], linewidth=2, marker="o", markersize=4,
                label=LABELS["xgboost"])
        ax.plot(t.index, t["random_forest"], color=RF_COLOR, linewidth=2, marker="o", markersize=4,
                label="Random Forest")
        ax.set_xticks(t.index[::2])
        ax.set_ylim(bottom=0)
        _style(ax, f"{metric} theo horizon ({segment})", "Horizon (giờ)", f"{metric} (điểm AQI)")
    axes[0].legend(frameon=False, fontsize=8, loc="lower right")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main():
    out = config.MODELS_DIR / "comparison"
    out.mkdir(parents=True, exist_ok=True)
    both = load_tables()
    for seg in sorted(both["segment"].unique()):
        for metric in ("MAE", "RMSE"):
            t = comparison(both, seg, metric)
            t.to_csv(out / f"rf_vs_xgb_{metric}_{seg}.csv")
            print(f"\n== {metric} ({seg}) ==\n{t.round(2).to_string()}")
        plot(both, seg, out / f"rf_vs_xgb_{seg}.png")


if __name__ == "__main__":
    main()
