"""EDA trước train: phân phối theo năm/mùa/nguồn, khoảng thiếu, AQI=500, bất thường PM.

    python -m src.eda      # -> models/eda/*.csv, *.png
"""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src import config  # noqa: E402
from src.data_loading import load_raw_dataset  # noqa: E402
from src.evaluate import GRID, INK, INK_MUTED, SEASONS, _style  # noqa: E402
from src.preprocessing import build_hourly_grid  # noqa: E402

SOURCE_COLORS = {"legacy": "#2a78d6", "open_meteo": "#eb6834"}
SOURCE_LABELS = {"legacy": "Nguồn cũ (2022 – 6/2025)", "open_meteo": "Open-Meteo (7/2025 –)"}
AQI_LEVELS = ([0, 50, 100, 150, 200, 300, 500],
              ["Tốt", "Trung bình", "Kém", "Xấu", "Rất xấu", "Nguy hại"])  # Bảng 3.2 báo cáo


def annotate(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["source"] = np.where(df["time"] < config.SOURCE_SWITCH, "legacy", "open_meteo")
    df["year"] = df["time"].dt.year
    df["season"] = df["time"].dt.month.map(SEASONS)
    df["pm25_jump_gt100"] = df["pm2_5"].diff().abs() > 100
    df["pm10_lt_pm25"] = df["pm10"] < df["pm2_5"]
    df["aqi_level"] = pd.cut(df["AQI"], AQI_LEVELS[0], labels=AQI_LEVELS[1], include_lowest=True)
    return df


def summary_tables(df: pd.DataFrame, grid: pd.DataFrame) -> dict[str, pd.DataFrame]:
    g = df.groupby(["source", "year"])
    by_year = g.agg(n=("AQI", "size"), AQI_mean=("AQI", "mean"), AQI_median=("AQI", "median"),
                    AQI_p95=("AQI", lambda s: s.quantile(0.95)), AQI_500=("AQI", lambda s: (s >= 500).sum()),
                    pm25_jump_gt100=("pm25_jump_gt100", "sum"), pm10_lt_pm25=("pm10_lt_pm25", "sum"))
    miss = grid.loc[~grid["observed"], "time"]
    by_year["missing_hours"] = [int((miss.dt.year == y).sum()) for _, y in by_year.index]
    by_season = df.groupby(["source", "season"])["AQI"].describe()[["count", "mean", "50%", "max"]]
    levels = pd.crosstab(df["source"], df["aqi_level"], normalize="index").mul(100)
    return {"summary_by_source_year": by_year.round(2), "aqi_by_source_season": by_season.round(2),
            "aqi_level_share_by_source_%": levels.round(2)}


def plot_monthly(df: pd.DataFrame, out_path) -> None:
    m = df.set_index("time")["AQI"].resample("MS")
    mean, q25, q75 = m.mean(), m.quantile(0.25), m.quantile(0.75)
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.fill_between(mean.index, q25, q75, color="#2a78d6", alpha=0.15, linewidth=0, label="Khoảng 25–75%")
    ax.plot(mean.index, mean, color="#2a78d6", linewidth=2, label="AQI trung bình tháng")
    ax.axvline(config.SOURCE_SWITCH, color=INK_MUTED, linestyle="--", linewidth=1)
    ax.annotate("Đổi nguồn dữ liệu\n01/07/2025", (config.SOURCE_SWITCH, ax.get_ylim()[1]), xytext=(6, -6),
                textcoords="offset points", va="top", fontsize=8, color=INK_MUTED)
    for name, t in (("train | val", config.TRAIN_END), ("val | test", config.VAL_END)):
        ax.axvline(t, color=GRID, linewidth=1.5)
        ax.annotate(name, (t, 0), xytext=(4, 4), textcoords="offset points", fontsize=8, color=INK_MUTED)
    ax.set_ylim(bottom=0)
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    _style(ax, "AQI theo tháng, Hà Nội 2022–2026", "Tháng", "AQI")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_by_source(df: pd.DataFrame, out_path) -> None:
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4))
    bins = np.arange(0, 505, 10)
    for src in ("legacy", "open_meteo"):
        d = df[df["source"] == src]
        a1.hist(d["AQI"], bins=bins, density=True, histtype="step", linewidth=2,
                color=SOURCE_COLORS[src], label=SOURCE_LABELS[src])
        hourly = d.groupby(d["time"].dt.hour)["AQI"].mean()
        a2.plot(hourly.index, hourly.values, color=SOURCE_COLORS[src], linewidth=2, marker="o",
                markersize=4, label=SOURCE_LABELS[src])
    a1.legend(frameon=False, fontsize=8)
    _style(a1, "Phân phối AQI theo nguồn", "AQI", "Mật độ")
    a2.set_xticks(range(0, 24, 3))
    a2.legend(frameon=False, fontsize=8)
    _style(a2, "AQI trung bình theo giờ trong ngày", "Giờ (UTC+7)", "AQI")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def run_eda(out_dir=config.EDA_DIR) -> dict[str, pd.DataFrame]:
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = load_raw_dataset()
    df = annotate(raw)
    tables = summary_tables(df, build_hourly_grid(raw))
    for name, t in tables.items():
        t.to_csv(out_dir / f"{name}.csv")
    plot_monthly(df, out_dir / "aqi_monthly.png")
    plot_by_source(df, out_dir / "aqi_by_source.png")
    return tables


if __name__ == "__main__":
    for name, t in run_eda().items():
        print(f"\n== {name} ==\n{t.to_string()}")
