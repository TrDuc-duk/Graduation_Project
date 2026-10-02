"""Cấu hình riêng cho Random Forest. Dữ liệu, horizon, split, seed lấy từ ml_xgb/src/config.py."""
from pathlib import Path

import rf  # noqa: F401  (thêm ml_xgb vào sys.path)
from src import config as base

ML_RF_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = ML_RF_ROOT / "models"
MODEL_VERSION = "rf-v1"

HORIZONS = base.HORIZONS
SEED = base.SEED
NAN_POLICY = "no_fill"  # RF so sánh trên cùng tập mẫu đầy đủ feature như XGBoost E0

# Tham số khởi điểm. min_samples_leaf và max_samples giới hạn kích thước model
# (RF không giới hạn sâu với ~28k mẫu sẽ tạo file hàng trăm MB mỗi horizon).
RF_PARAMS = dict(
    n_estimators=300,
    max_depth=None,
    min_samples_leaf=10,
    max_features=0.33,
    max_samples=0.7,
    bootstrap=True,
    n_jobs=-1,
    random_state=SEED,
)

# Lưới tham số chọn bằng validation trên vài horizon đại diện.
# Vòng đầu (leaf 5–25, max_features 0.2–0.5): max_features=0.5 kém nhất ở h=24/72, 0.2 tốt nhất
# nhưng nằm ở biên lưới, leaf lớn giảm overfit mà không làm val kém đi -> dời lưới về phía đó.
TUNE_HORIZONS = [3, 24, 72]
PARAM_GRID = {
    "min_samples_leaf": [10, 25, 50, 100],
    "max_features": [0.1, 0.2, 0.33],
}
TUNE_N_ESTIMATORS = 150  # ít cây hơn khi tune cho nhanh; xếp hạng tham số ít phụ thuộc số cây
