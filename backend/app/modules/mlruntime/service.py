"""Giao diện công khai của mlruntime cho module khác: thông tin phiên bản model (không lộ repository/models)."""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mlruntime import repository


@dataclass(frozen=True)
class ModelInfo:
    """Thông tin một phiên bản model dùng khi trình bày dự báo."""

    id: int
    model_version: str
    required_history_hours: int
    summary: dict  # theo horizon (chuỗi): n_trees, val/test MAE, RMSE lúc train


async def model_info(session: AsyncSession, model_id: int) -> ModelInfo | None:
    """Thông tin phiên bản model theo id (kể cả bản đã ngừng dùng, để trình bày dự báo cũ)."""
    m = await repository.get(session, model_id)
    if m is None:
        return None
    return ModelInfo(m.id, m.model_version, m.required_history_hours, m.summary)
