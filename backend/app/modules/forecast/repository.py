"""Truy vấn SQL của module forecast. Không commit."""

from datetime import date, datetime

from sqlalchemy import insert, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.forecast.models import Forecast, ForecastAttempt, ForecastInput, ForecastInputHistory, ForecastRun


async def lock_scheduled_run(
    session: AsyncSession, node_id: int, model_id: int, input_hour: datetime
) -> ForecastRun | None:
    """Lần chạy theo lịch của (node, model, giờ), khóa dòng; đang bị tiến trình khác khóa thì coi như không thấy."""
    stmt = (
        select(ForecastRun)
        .where(
            ForecastRun.node_id == node_id,
            ForecastRun.model_id == model_id,
            ForecastRun.input_hour == input_hour,
            ForecastRun.trigger == "schedule",
        )
        .with_for_update(skip_locked=True)
    )
    return (await session.scalars(stmt)).one_or_none()


async def scheduled_run_exists(session: AsyncSession, node_id: int, model_id: int, input_hour: datetime) -> bool:
    """Đã có lần chạy theo lịch (kể cả đang bị khóa) cho (node, model, giờ) chưa."""
    stmt = select(ForecastRun.id).where(
        ForecastRun.node_id == node_id,
        ForecastRun.model_id == model_id,
        ForecastRun.input_hour == input_hour,
        ForecastRun.trigger == "schedule",
    )
    return (await session.scalar(stmt)) is not None


async def insert_run(session: AsyncSession, **values: object) -> ForecastRun | None:
    """Tạo lần chạy; trùng lần chạy theo lịch (ux_forecast_runs_schedule) thì trả None, không lỗi."""
    stmt = pg_insert(ForecastRun).values(**values).on_conflict_do_nothing().returning(ForecastRun.id)
    run_id = await session.scalar(stmt)
    return None if run_id is None else await session.get(ForecastRun, run_id)


async def get_run(session: AsyncSession, run_id: int, *, for_update: bool = False) -> ForecastRun | None:
    """Một lần chạy theo id."""
    stmt = select(ForecastRun).where(ForecastRun.id == run_id)
    return (await session.scalars(stmt.with_for_update() if for_update else stmt)).one_or_none()


async def add_attempt(session: AsyncSession, **values: object) -> int:
    """Ghi một lần thử mới (đang chạy), trả id."""
    return await session.scalar(insert(ForecastAttempt).values(**values).returning(ForecastAttempt.id))


async def get_attempt(session: AsyncSession, attempt_id: int) -> ForecastAttempt | None:
    """Một lần thử theo id."""
    return await session.get(ForecastAttempt, attempt_id)


async def latest_attempt(session: AsyncSession, run_id: int) -> ForecastAttempt | None:
    """Lần thử gần nhất của một lần chạy."""
    stmt = (
        select(ForecastAttempt)
        .where(ForecastAttempt.run_id == run_id)
        .order_by(ForecastAttempt.attempt_no.desc())
        .limit(1)
    )
    return (await session.scalars(stmt)).one_or_none()


async def insert_results(
    session: AsyncSession,
    forecasts: list[dict],
    features: dict,
    history: dict,
) -> None:
    """Ghi 24 mốc dự báo, feature đã dùng và các dòng giờ đã dùng của một lần chạy thành công."""
    await session.execute(insert(Forecast), forecasts)
    await session.execute(insert(ForecastInput).values(**features))
    await session.execute(insert(ForecastInputHistory).values(**history))


async def forecasts_of(session: AsyncSession, run_id: int) -> list[Forecast]:
    """Các mốc dự báo của một lần chạy, theo horizon."""
    stmt = select(Forecast).where(Forecast.run_id == run_id).order_by(Forecast.horizon_h)
    return list((await session.scalars(stmt)).all())


async def latest_success(session: AsyncSession, node_id: int, kinds: tuple[str, ...]) -> ForecastRun | None:
    """Lần chạy `ok` mới nhất được công khai (loại trong `kinds`), xếp theo input_hour rồi issued_at (R23)."""
    stmt = (
        select(ForecastRun)
        .where(ForecastRun.node_id == node_id, ForecastRun.status == "ok", ForecastRun.issue_kind.in_(kinds))
        .order_by(ForecastRun.input_hour.desc(), ForecastRun.issued_at.desc())
        .limit(1)
    )
    return (await session.scalars(stmt)).one_or_none()


async def latest_run(session: AsyncSession, node_id: int) -> ForecastRun | None:
    """Lần chạy mới nhất của node, mọi trạng thái và loại (R23)."""
    stmt = (
        select(ForecastRun)
        .where(ForecastRun.node_id == node_id)
        .order_by(ForecastRun.input_hour.desc(), ForecastRun.started_at.desc())
        .limit(1)
    )
    return (await session.scalars(stmt)).one_or_none()


async def live_mae(
    session: AsyncSession, node_id: int, model_id: int, since: date, kinds: tuple[str, ...]
) -> dict[int, tuple[int, float]]:
    """{horizon: (số cặp, MAE)} thực tế của node và model từ ngày `since`, trên các loại phát hành `kinds`."""
    stmt = text(
        "SELECT horizon_h, sum(n) AS n, sum(sum_abs_err) AS abs_err FROM forecast_accuracy_daily "
        "WHERE node_id = :n AND model_id = :m AND day >= :since AND issue_kind = ANY(:kinds) GROUP BY horizon_h"
    )
    result = await session.execute(stmt, {"n": node_id, "m": model_id, "since": since, "kinds": list(kinds)})
    return {r.horizon_h: (int(r.n), r.abs_err / r.n) for r in result if r.n}
