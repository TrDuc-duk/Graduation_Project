"""Truy vấn SQL của module hourly. Không commit."""

from dataclasses import asdict
from datetime import datetime

from sqlalchemy import Row, delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.timeutil import LOCAL_TZ
from app.modules.hourly.aggregate import HourAggregate
from app.modules.hourly.models import NodeHourly


async def get_hours(session: AsyncSession, node_id: int, start: datetime, end: datetime) -> list[NodeHourly]:
    """Các dòng giờ của node có nhãn trong (start, end], cũ → mới."""
    stmt = (
        select(NodeHourly)
        .where(NodeHourly.node_id == node_id, NodeHourly.hour_end > start, NodeHourly.hour_end <= end)
        .order_by(NodeHourly.hour_end)
    )
    return list((await session.scalars(stmt)).all())


async def latest_closed(session: AsyncSession, node_id: int, since: datetime) -> NodeHourly | None:
    """Dòng giờ đã đóng mới nhất của node có nhãn sau `since`."""
    stmt = (
        select(NodeHourly)
        .where(NodeHourly.node_id == node_id, NodeHourly.is_closed, NodeHourly.hour_end > since)
        .order_by(NodeHourly.hour_end.desc())
        .limit(1)
    )
    return (await session.scalars(stmt)).one_or_none()


async def get_hour(session: AsyncSession, node_id: int, hour_end: datetime) -> NodeHourly | None:
    """Dòng giờ của node tại nhãn `hour_end` (nếu có)."""
    return await session.get(NodeHourly, (node_id, hour_end), populate_existing=True)


async def nodes_with_rows(session: AsyncSession, hour_end: datetime) -> list[int]:
    """Node đã có dòng ở giờ `hour_end`."""
    return list((await session.scalars(select(NodeHourly.node_id).where(NodeHourly.hour_end == hour_end))).all())


async def upsert_hour(
    session: AsyncSession, node_id: int, agg: HourAggregate, *, is_closed: bool, revision: int, at: datetime
) -> None:
    """Ghi (thêm hoặc thay) một dòng giờ với kết quả tổng hợp, trạng thái đóng và revision cho trước."""
    values = {**asdict(agg), "node_id": node_id, "is_closed": is_closed, "revision": revision, "computed_at": at}
    stmt = insert(NodeHourly).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[NodeHourly.node_id, NodeHourly.hour_end],
        set_={k: stmt.excluded[k] for k in values if k not in ("node_id", "hour_end")},
    )
    await session.execute(stmt)


async def delete_hour(session: AsyncSession, node_id: int, hour_end: datetime) -> None:
    """Xóa dòng giờ (khi giờ không còn mẫu nào, vd mọi bản đều bị thay)."""
    await session.execute(delete(NodeHourly).where(NodeHourly.node_id == node_id, NodeHourly.hour_end == hour_end))


async def day_means(session: AsyncSession, node_id: int, start: datetime, end: datetime) -> list[Row]:
    """Trung bình theo ngày (giờ Việt Nam) của các giờ có nhãn trong (start, end].

    Ngày của giờ `h` là ngày chứa cửa sổ (h−1, h], tức ngày của `h − 1 giờ`: 24 giờ 01:00…24:00 thuộc cùng một ngày.
    Mỗi giờ có dữ liệu góp một giá trị (trung bình các trung bình giờ, bỏ null).
    """
    stmt = text(
        "SELECT ((hour_end - interval '1 hour') AT TIME ZONE :tz)::date AS day, count(*) AS n_hours, "
        "avg(pm25_avg) AS pm25, avg(pm10_avg) AS pm10, avg(temperature_avg) AS temperature, "
        "avg(humidity_avg) AS humidity, avg(co2_avg) AS co2, avg(tvoc_avg) AS tvoc "
        "FROM node_hourly WHERE node_id = :node_id AND hour_end > :start AND hour_end <= :end "
        "GROUP BY 1 ORDER BY 1"
    )
    params = {"tz": LOCAL_TZ.key, "node_id": node_id, "start": start, "end": end}
    return list((await session.execute(stmt, params)).all())


async def aqi_by_hour_of_day(session: AsyncSession, node_id: int, since: datetime) -> list[Row]:
    """AQI giờ trung bình theo giờ trong ngày (giờ Việt Nam của nhãn `h`) của các giờ đã đóng sau `since`."""
    stmt = text(
        "SELECT extract(hour FROM hour_end AT TIME ZONE :tz)::int AS hour_of_day, "
        "avg(aqi)::double precision AS aqi, count(*) AS n_hours "
        "FROM node_hourly WHERE node_id = :node_id AND hour_end > :since AND is_closed AND aqi IS NOT NULL "
        "GROUP BY 1 ORDER BY 1"
    )
    params = {"tz": LOCAL_TZ.key, "node_id": node_id, "since": since}
    return list((await session.execute(stmt, params)).all())


async def enqueue(session: AsyncSession, node_id: int, hour_end: datetime) -> None:
    """Xếp hàng tính lại (node, giờ); đã có trong hàng thì bỏ qua."""
    await session.execute(
        text("INSERT INTO hourly_recompute_queue (node_id, hour_end) VALUES (:n, :h) ON CONFLICT DO NOTHING"),
        {"n": node_id, "h": hour_end},
    )


async def queued(session: AsyncSession, closable_until: datetime, limit: int) -> list[Row]:
    """Các mục trong hàng đợi có giờ đã qua mốc đóng (`hour_end ≤ closable_until`), cũ trước."""
    stmt = text(
        "SELECT node_id, hour_end FROM hourly_recompute_queue WHERE hour_end <= :until "
        "ORDER BY queued_at, node_id, hour_end LIMIT :n"
    )
    return list((await session.execute(stmt, {"until": closable_until, "n": limit})).all())


async def dequeue(session: AsyncSession, node_id: int, hour_end: datetime) -> None:
    """Bỏ (node, giờ) khỏi hàng đợi tính lại."""
    await session.execute(
        text("DELETE FROM hourly_recompute_queue WHERE node_id = :n AND hour_end = :h"), {"n": node_id, "h": hour_end}
    )
