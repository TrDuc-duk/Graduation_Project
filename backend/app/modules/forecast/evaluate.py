"""Đối chiếu dự báo với thực tế (backend_design 8.5, R8).

- Lần đầu (bước 3 của đường ống): giờ h đóng xong thì điền `actual_aqi` = `node_hourly.aqi`, `actual_revision`,
  `evaluated_at` cho mọi dự báo có `target_hour = h`; giờ đích không có dữ liệu → `actual_aqi` NULL.
- Đánh giá lại (outbox `hourly_revised`): chỉ khi revision mới lớn hơn `actual_revision` đã lưu.
- Sau mỗi lần đổi, tính lại `forecast_accuracy_daily` của (node, ngày) liên quan — ghi đè nên idempotent.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import LOCAL_TZ, to_local

_DAY = timedelta(days=1)


async def evaluate_target_hour(session: AsyncSession, hour_end: datetime, now: datetime) -> int:
    """Bước 3: đối chiếu lần đầu các dự báo có giờ đích `hour_end`; trả số mốc đã đối chiếu."""
    rows = (
        await session.execute(
            text(
                "UPDATE forecasts f SET "
                "actual_aqi = (SELECT h.aqi FROM node_hourly h "
                "WHERE h.node_id = f.node_id AND h.hour_end = f.target_hour), "
                "actual_revision = (SELECT h.revision FROM node_hourly h "
                "WHERE h.node_id = f.node_id AND h.hour_end = f.target_hour), "
                "evaluated_at = :now "
                "WHERE f.target_hour = :h AND f.evaluated_at IS NULL RETURNING f.node_id"
            ),
            {"h": hour_end, "now": now},
        )
    ).all()
    for node_id in {r.node_id for r in rows}:
        await recompute_accuracy(session, node_id, to_local(hour_end).date())
    return len(rows)


async def apply_revision(session: AsyncSession, node_id: int, hour_end: datetime, revision: int, now: datetime) -> int:
    """Đánh giá lại khi giờ đích đã đóng được tính lại (`revision` mới); dự báo chưa đối chiếu lần đầu thì để bước 3.

    Trả số mốc được cập nhật. Revision cũ hơn hoặc bằng bản đã dùng thì bỏ qua (sự kiện chạy lại không làm sai).
    """
    rows = (
        await session.execute(
            text(
                "UPDATE forecasts f SET actual_aqi = h.aqi, actual_revision = h.revision, evaluated_at = :now "
                "FROM node_hourly h "
                "WHERE f.node_id = :n AND f.target_hour = :h AND f.evaluated_at IS NOT NULL "
                "AND h.node_id = f.node_id AND h.hour_end = f.target_hour AND h.revision >= :rev "
                "AND (f.actual_revision IS NULL OR f.actual_revision < h.revision) "
                "RETURNING f.run_id"
            ),
            {"n": node_id, "h": hour_end, "rev": revision, "now": now},
        )
    ).all()
    if rows:
        await recompute_accuracy(session, node_id, to_local(hour_end).date())
    return len(rows)


async def recompute_accuracy(session: AsyncSession, node_id: int, day: date) -> None:
    """Tính lại mọi dòng `forecast_accuracy_daily` của node trong `day` (giờ Việt Nam của target_hour).

    Theo (model, horizon, loại phát hành): số cặp, tổng |sai số|, tổng bình phương, tổng sai số (dự báo − thực tế),
    và sai số của baseline persistence trên các cặp có `persistence_aqi` (R34).
    """
    start = datetime(day.year, day.month, day.day, tzinfo=LOCAL_TZ)
    params = {"n": node_id, "day": day, "start": start, "end": start + _DAY}
    await session.execute(text("DELETE FROM forecast_accuracy_daily WHERE node_id = :n AND day = :day"), params)
    await session.execute(
        text(
            """
            INSERT INTO forecast_accuracy_daily (node_id, model_id, horizon_h, day, issue_kind, n, sum_abs_err,
                sum_sq_err, sum_err, sum_abs_err_persistence, n_persistence, updated_at)
            SELECT f.node_id, r.model_id, f.horizon_h, :day, r.issue_kind, count(*),
                   sum(abs(f.predicted_aqi - f.actual_aqi)), sum((f.predicted_aqi - f.actual_aqi) ^ 2),
                   sum(f.predicted_aqi - f.actual_aqi),
                   coalesce(sum(abs(f.persistence_aqi - f.actual_aqi)) FILTER (WHERE f.persistence_aqi IS NOT NULL), 0),
                   count(f.persistence_aqi), now()
            FROM forecasts f JOIN forecast_runs r ON r.id = f.run_id
            WHERE f.node_id = :n AND f.target_hour >= :start AND f.target_hour < :end AND f.actual_aqi IS NOT NULL
            GROUP BY f.node_id, r.model_id, f.horizon_h, r.issue_kind
            """
        ),
        params,
    )
