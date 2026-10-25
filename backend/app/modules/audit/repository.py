"""Truy vấn SQL của module audit. Không commit."""

from datetime import datetime

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditLog


async def insert_log(session: AsyncSession, **values: object) -> None:
    """Thêm một dòng nhật ký."""
    await session.execute(insert(AuditLog).values(**values))


async def search(
    session: AsyncSession, filters: dict, start: datetime | None, end: datetime | None, offset: int, limit: int
) -> tuple[list[AuditLog], int]:
    """Nhật ký mới trước, lọc theo các cột bằng nhau trong `filters` và khoảng thời gian; trả (trang, tổng số)."""
    conds = [getattr(AuditLog, k) == v for k, v in filters.items() if v is not None]
    if start is not None:
        conds.append(AuditLog.occurred_at >= start)
    if end is not None:
        conds.append(AuditLog.occurred_at < end)
    total = await session.scalar(select(func.count()).select_from(AuditLog).where(*conds))
    stmt = select(AuditLog).where(*conds).order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
    items = (await session.scalars(stmt.offset(offset).limit(limit))).all()
    return list(items), int(total or 0)
