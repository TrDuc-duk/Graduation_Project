"""Random Forest dự báo AQI (3h → 72h).

Dùng lại phần dữ liệu của ml_xgb/src (lưới giờ, feature, nhãn, split, baseline, metric) để
hai model được so trên cùng feature và cùng tập validation/test.
"""
import sys
from pathlib import Path

_ML_XGB = Path(__file__).resolve().parents[2] / "ml_xgb"
if str(_ML_XGB) not in sys.path:
    sys.path.insert(0, str(_ML_XGB))
