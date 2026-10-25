"""Cầu nối tới code ML dùng chung `ml/ml_xgb/src` (backend_design 8.2, P4): không chép công thức, chỉ gọi hàm.

Dùng bộ model đã nạp trong bộ nhớ (registry) thay vì đọc file mỗi lần như `src.predict.predict`, nhưng cùng
cách dựng feature (`build_inference_features`) và cùng cách gọi model (`predict_with_model` với `n_trees`).
"""

import pandas as pd
from src.aqi import compute_aqi
from src.predict import InferenceDataError, build_inference_features
from src.train import predict_with_model

from app.modules.mlruntime.registry import LoadedBundle

__all__ = ["InferenceDataError", "build_features", "compute_aqi", "predict"]


def build_features(history: pd.DataFrame, meta: dict, t: pd.Timestamp, now: pd.Timestamp) -> pd.DataFrame:
    """Một hàng feature tại `t` (giờ Việt Nam, không múi giờ). Thiếu lịch sử hoặc dữ liệu quá cũ so với `now`
    → InferenceDataError. Không bao giờ truyền `now=None` (luôn kiểm tra độ mới, R16)."""
    return build_inference_features(history, meta, t, now)


def predict(bundle: LoadedBundle, history: pd.DataFrame, t: pd.Timestamp, now: pd.Timestamp) -> tuple[dict, dict]:
    """Dự báo mọi horizon của bộ model tại `t`. Trả ({horizon: AQI dự báo}, {khóa feature: hàng feature}).

    Các horizon cùng (nan_policy, include_extra, feature_columns) dùng chung một hàng feature, như `src.predict`.
    """
    preds, cache = {}, {}
    for h in bundle.horizons:
        meta = bundle.metas[h]
        key = (meta["nan_policy"]["name"], meta.get("include_extra_features", False), tuple(meta["feature_columns"]))
        if key not in cache:
            cache[key] = build_features(history, meta, t, now)
        feats = cache[key]
        preds[h] = float(predict_with_model(bundle.models[h], feats[meta["feature_columns"]], meta["n_trees"])[0])
    return preds, cache
