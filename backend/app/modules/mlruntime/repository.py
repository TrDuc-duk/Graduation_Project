"""Truy vấn SQL của module mlruntime. Không commit."""

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.mlruntime.models import MlModel


async def all_models(session: AsyncSession) -> list[MlModel]:
    """Mọi phiên bản model đã biết, theo id."""
    return list((await session.scalars(select(MlModel).order_by(MlModel.id))).all())


async def get(session: AsyncSession, model_id: int, *, for_update: bool = False) -> MlModel | None:
    """Một phiên bản model theo id."""
    stmt = select(MlModel).where(MlModel.id == model_id)
    return (await session.scalars(stmt.with_for_update() if for_update else stmt)).one_or_none()


async def active(session: AsyncSession) -> MlModel | None:
    """Phiên bản đang kích hoạt (tối đa một, ux_ml_models_one_active)."""
    return (await session.scalars(select(MlModel).where(MlModel.is_active))).one_or_none()


async def deactivate_all(session: AsyncSession) -> None:
    """Bỏ kích hoạt mọi phiên bản (trước khi kích hoạt bản khác, hoặc khi bản đang dùng hỏng)."""
    await session.execute(update(MlModel).where(MlModel.is_active).values(is_active=False))


async def set_active(session: AsyncSession, model_id: int, at: datetime, user_id: int | None) -> None:
    """Kích hoạt một phiên bản."""
    await session.execute(
        update(MlModel).where(MlModel.id == model_id).values(is_active=True, activated_at=at, activated_by=user_id)
    )
