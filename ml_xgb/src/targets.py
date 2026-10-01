"""Nhãn target_AQI_h{h} = AQI quan sát gốc tại t+h, tính trên lưới giờ đầy đủ."""
import pandas as pd

from src import config


def target_column(h: int) -> str:
    return f"target_AQI_h{h}"


def add_targets(grid: pd.DataFrame, horizons=config.HORIZONS) -> pd.DataFrame:
    """Dùng AQI_observed (không bao giờ bị điền) nên giờ thiếu cho nhãn NaN."""
    if "AQI_observed" not in grid:
        raise ValueError("Thiếu cột AQI_observed; chạy build_hourly_grid trước")
    cols = {target_column(h): grid["AQI_observed"].shift(-h) for h in horizons}
    return pd.concat([grid, pd.DataFrame(cols, index=grid.index)], axis=1)
