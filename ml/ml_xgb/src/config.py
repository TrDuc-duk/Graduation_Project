"""Hằng số dùng chung cho toàn bộ pipeline. Các module khác không hardcode lại."""
from pathlib import Path

import pandas as pd

# Đường dẫn suy ra từ vị trí file, không phụ thuộc tên thư mục dự án ML (vd ml_xgb/)
ML_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = ML_ROOT.parent
DATA_PATH = REPO_ROOT / "data" / "dataset.csv"
EXPECTED_DATASET_SHA256 = "45b710f8f7cc701ee8f8885704c1bcec4b7aa74ac2f34053a56bc86fd2d1e7c4"

MODELS_DIR = ML_ROOT / "models"
METRICS_DIR = MODELS_DIR / "metrics"
PLOTS_DIR = MODELS_DIR / "plots"
EDA_DIR = MODELS_DIR / "eda"
LEGACY_MODELS_DIR = MODELS_DIR / "legacy_only"  # split riêng trong đoạn nguồn cũ

HORIZONS = list(range(3, 73, 3))
BASE_COLUMNS = ["AQI", "pm10", "pm2_5", "Humidity", "Temperature"]
LAG_HOURS = [1, 3, 6, 12, 24, 48, 72]
ROLLING_WINDOWS = [3, 6, 12, 24, 72]
ROLLING_STATS = ["mean", "std", "min", "max"]

# Mốc đổi nguồn dữ liệu (file năm -> Open-Meteo)
SOURCE_SWITCH = pd.Timestamp("2025-07-01 00:00:00")

# Mốc cắt split (nửa kín [start, end), giờ địa phương UTC+7, naive) trên lưới 41.136 giờ
TRAIN_START = pd.Timestamp("2022-01-13 00:00:00")
TRAIN_END = pd.Timestamp("2025-04-26 19:00:00")
VAL_END = pd.Timestamp("2026-01-08 21:00:00")
TEST_END = pd.Timestamp("2026-09-23 00:00:00")

NAN_POLICY = "no_fill"  # no_fill | ffill3h | xgb_native_nan
FFILL_LIMIT_HOURS = 3
SEED = 42

XGB_PARAMS = dict(
    n_estimators=1000,
    max_depth=6,
    learning_rate=0.03,
    subsample=0.8,
    colsample_bytree=0.8,
    objective="reg:squarederror",
    eval_metric="rmse",
    random_state=SEED,
    n_jobs=-1,
)
EARLY_STOPPING_ROUNDS = 50
MODEL_VERSION = "v1"
