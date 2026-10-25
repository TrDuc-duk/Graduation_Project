"""Truy vấn SQL của module pipeline. Không commit."""

from datetime import datetime

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.pipeline.models import HourPipeline


async def latest_hour(session: AsyncSession) -> datetime | None:
    """Nhãn giờ lớn nhất đã có trong `hour_pipeline`."""
    return await session.scalar(select(func.max(HourPipeline.hour_end)))


async def ensure_hours(session: AsyncSession, hours: list[datetime]) -> None:
    """Thêm dòng tiến độ cho các giờ chưa có (giờ đã có giữ nguyên)."""
    if hours:
        await session.execute(
            text(
                "INSERT INTO hour_pipeline (hour_end) SELECT unnest(CAST(:h AS timestamptz[])) ON CONFLICT DO NOTHING"
            ),
            {"h": hours},
        )


async def unfinished(
    session: AsyncSession, done_columns: tuple[str, ...], since: datetime, until: datetime, limit: int
) -> list[HourPipeline]:
    """Các giờ trong [since, until] còn bước chưa xong (một cột trong `done_columns` là NULL), cũ trước."""
    pending = or_(*(getattr(HourPipeline, c).is_(None) for c in done_columns))
    stmt = (
        select(HourPipeline)
        .where(HourPipeline.hour_end >= since, HourPipeline.hour_end <= until, pending)
        .order_by(HourPipeline.hour_end)
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


async def mark_step_done(
    session: AsyncSession, hour_end: datetime, column: str, at: datetime, extra: dict | None = None
) -> None:
    """Ghi bước `column` của giờ đã xong (kèm cột phụ như `forecast_kind`); xóa lỗi cũ."""
    await session.execute(
        update(HourPipeline)
        .where(HourPipeline.hour_end == hour_end)
        .values({column: at, "last_error": None, "updated_at": func.now(), **(extra or {})})
    )


async def mark_error(session: AsyncSession, hour_end: datetime, error: str) -> None:
    """Bước lỗi: tăng số lần thử, ghi lỗi; lần kích hoạt sau thử lại."""
    await session.execute(
        update(HourPipeline)
        .where(HourPipeline.hour_end == hour_end)
        .values(attempts=HourPipeline.attempts + 1, last_error=error[:2000], updated_at=func.now())
    )


async def progress_rows(session: AsyncSession, done_columns: tuple[str, ...], limit: int) -> list[HourPipeline]:
    """Các giờ chưa xong hoặc đang lỗi, mới trước (cho trang Hệ thống)."""
    pending = or_(HourPipeline.last_error.is_not(None), *(getattr(HourPipeline, c).is_(None) for c in done_columns))
    stmt = select(HourPipeline).where(pending).order_by(HourPipeline.hour_end.desc()).limit(limit)
    return list((await session.scalars(stmt)).all())
