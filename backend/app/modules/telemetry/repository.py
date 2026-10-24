"""Truy vấn SQL của module telemetry. Không commit."""

from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, Row, and_, insert, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.telemetry.models import IngestBatch, Measurement
from app.modules.telemetry.qc import EXCLUDE_MASK, QcFlag


async def insert_batch(session: AsyncSession, **fields: object) -> int:
    """Thêm một dòng ingest_batches, trả id."""
    return await session.scalar(insert(IngestBatch).values(**fields).returning(IngestBatch.id))


async def update_batch(session: AsyncSession, batch_id: int, received_at: datetime, **fields: object) -> None:
    """Cập nhật thống kê của một batch đã ghi."""
    await session.execute(
        update(IngestBatch).where(IngestBatch.id == batch_id, IngestBatch.received_at == received_at).values(**fields)
    )


async def insert_measurements(session: AsyncSession, rows: list[dict]) -> list[int]:
    """Chèn nhiều số đo, trả id theo đúng thứ tự `rows`."""
    if not rows:
        return []
    stmt = insert(Measurement).returning(Measurement.id, sort_by_parameter_order=True)
    return list((await session.scalars(stmt, rows)).all())


async def find_copies(session: AsyncSession, node_id: int, hashes: list[int], received_since: datetime) -> list[Row]:
    """Bản sao còn hiệu lực (chưa SUPERSEDED) của node có payload_hash trong `hashes`, nhận từ `received_since`.

    Điều kiện measured_at ≥ received_since − 1 ngày để TimescaleDB chỉ quét chunk gần (database_design 6).
    """
    stmt = select(
        Measurement.id, Measurement.measured_at, Measurement.received_at, Measurement.payload_hash, Measurement.qc_flags
    ).where(
        Measurement.node_id == node_id,
        Measurement.payload_hash.in_(hashes),
        Measurement.received_at >= received_since,
        Measurement.measured_at >= received_since - timedelta(days=1),
        Measurement.superseded_at.is_(None),
    )
    return list((await session.execute(stmt)).all())


async def mark_superseded(session: AsyncSession, keys: list[tuple[int, datetime]], at: datetime) -> None:
    """Gắn cờ SUPERSEDED và superseded_at cho các bản bị bản sao tốt hơn thay (luôn đi cùng nhau, R21)."""
    for mid, measured_at in keys:
        await session.execute(
            update(Measurement)
            .where(Measurement.id == mid, Measurement.measured_at == measured_at)
            .values(qc_flags=Measurement.qc_flags.op("|")(int(QcFlag.SUPERSEDED)), superseded_at=at)
        )


async def nodes_with_trusted_data(session: AsyncSession, since: datetime) -> list[int]:
    """Node có số đo đáng tin nhận từ `since`."""
    stmt = (
        select(Measurement.node_id)
        .where(
            Measurement.received_at >= since,
            Measurement.measured_at >= since - timedelta(days=1),
            Measurement.qc_flags.op("&")(int(EXCLUDE_MASK)) == 0,
        )
        .distinct()
    )
    return list((await session.scalars(stmt)).all())


async def trusted_with_batch(session: AsyncSession, node_id: int, since: datetime) -> list[Row]:
    """Số đo đáng tin của node từ `since`, kèm thông tin batch (nghi cũ, số lần thử), theo thứ tự nhận."""
    stmt = (
        select(
            Measurement.gateway_id,
            Measurement.batch_id,
            Measurement.received_at,
            Measurement.seq,
            Measurement.msg_id,
            Measurement.time_source,
            IngestBatch.stale_suspected,
            IngestBatch.attempts,
        )
        .join(
            IngestBatch,
            (IngestBatch.id == Measurement.batch_id) & (IngestBatch.received_at == Measurement.received_at),
        )
        .where(
            Measurement.node_id == node_id,
            Measurement.received_at >= since,
            Measurement.measured_at >= since - timedelta(days=1),
            Measurement.qc_flags.op("&")(int(EXCLUDE_MASK)) == 0,
        )
        .order_by(Measurement.received_at, Measurement.seq)
    )
    return list((await session.execute(stmt)).all())


async def readings(session: AsyncSession, node_id: int, since: datetime, limit: int) -> list[Measurement]:
    """Số đo còn hiệu lực (bỏ bản SUPERSEDED) của node có measured_at từ `since`, cũ → mới, tối đa `limit` dòng."""
    stmt = (
        select(Measurement)
        .where(Measurement.node_id == node_id, Measurement.measured_at >= since, Measurement.superseded_at.is_(None))
        .order_by(Measurement.measured_at.desc(), Measurement.received_at.desc(), Measurement.seq.desc())
        .limit(limit)
    )
    return list(reversed((await session.scalars(stmt)).all()))


async def hourly_means(session: AsyncSession, node_id: int, since: datetime) -> list[Row]:
    """Trung bình theo giờ của số đo dùng được cho tổng hợp (không mang cờ EXCLUDE_MASK) có measured_at > `since`.

    Nhãn giờ `h` là cửa sổ (h−1, h] (backend_design 11.4); giờ không có số đo thì không có dòng.
    """
    stmt = text(
        "SELECT time_bucket('1 hour', measured_at - interval '1 microsecond') + interval '1 hour' AS hour, "
        "count(*) AS n_samples, avg(pm25) AS pm25, avg(pm10) AS pm10, "
        "avg(co2)::double precision AS co2, avg(tvoc)::double precision AS tvoc, "
        "avg(temperature) AS temperature, avg(humidity) AS humidity "
        "FROM measurements "
        "WHERE node_id = :node_id AND measured_at > :since AND superseded_at IS NULL AND qc_flags & :mask = 0 "
        "GROUP BY 1 ORDER BY 1"
    )
    params = {"node_id": node_id, "since": since, "mask": int(EXCLUDE_MASK)}
    return list((await session.execute(stmt, params)).all())


async def latest_reading(session: AsyncSession, node_id: int) -> Measurement | None:
    """Số đo còn hiệu lực mới nhất của node (theo thời điểm nhận)."""
    stmt = (
        select(Measurement)
        .where(Measurement.node_id == node_id, Measurement.superseded_at.is_(None))
        .order_by(Measurement.received_at.desc(), Measurement.seq.desc())
        .limit(1)
    )
    return (await session.scalars(stmt)).one_or_none()


async def latest_trusted_reading(session: AsyncSession, node_id: int) -> Measurement | None:
    """Số đo mới nhất (theo thời điểm nhận) dùng được cho số đo hiện tại: không mang cờ EXCLUDE_MASK."""
    stmt = (
        select(Measurement)
        .where(Measurement.node_id == node_id, Measurement.qc_flags.op("&")(int(EXCLUDE_MASK)) == 0)
        .order_by(Measurement.received_at.desc(), Measurement.seq.desc())
        .limit(1)
    )
    return (await session.scalars(stmt)).one_or_none()


async def trusted_series(session: AsyncSession, node_id: int, since: datetime) -> list[Row]:
    """Các số đo dùng được cho tổng hợp có measured_at > `since` (cũ → mới), chỉ các cột môi trường."""
    stmt = (
        select(
            Measurement.measured_at,
            Measurement.aqi_instant,
            Measurement.pm25,
            Measurement.pm10,
            Measurement.temperature,
            Measurement.humidity,
        )
        .where(
            Measurement.node_id == node_id,
            Measurement.measured_at > since,
            Measurement.qc_flags.op("&")(int(EXCLUDE_MASK)) == 0,
        )
        .order_by(Measurement.measured_at)
    )
    return list((await session.execute(stmt)).all())


async def last_trusted_pm25(session: AsyncSession, node_id: int, since: datetime) -> float | None:
    """PM2.5 của số đo đáng tin mới nhất từ `since` (để xét PM_SPIKE)."""
    stmt = (
        select(Measurement.pm25)
        .where(
            Measurement.node_id == node_id,
            Measurement.measured_at >= since,
            Measurement.pm25.is_not(None),
            Measurement.qc_flags.op("&")(int(EXCLUDE_MASK)) == 0,
        )
        .order_by(Measurement.measured_at.desc(), Measurement.received_at.desc(), Measurement.seq.desc())
        .limit(1)
    )
    return await session.scalar(stmt)


def as_of_filter(cutoff: datetime | None) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
    """Điều kiện chọn bản ghi theo trạng thái tại `cutoff` (backend_design 7, R21); trả (được chọn, bị loại).

    - Được chọn: đã nhận (`received_at ≤ cutoff`) và chưa bị bản sao tốt hơn thay tại lúc đó.
    - Bị loại (chỉ đếm `n_excluded`): batch nghi cũ (`TIME_UNRELIABLE`, đặt lúc nhận, không đổi) hoặc
      chưa được tin cậy tại lúc đó (`trusted_at` NULL hoặc sau cutoff).
    `cutoff=None` là trạng thái hiện tại, tương đương as-of "bây giờ" vì cờ luôn khớp hai cột thời điểm (CHECK).
    """
    unreliable = Measurement.qc_flags.op("&")(int(QcFlag.TIME_UNRELIABLE)) != 0
    if cutoff is None:
        selected = Measurement.superseded_at.is_(None)
        untrusted = Measurement.trusted_at.is_(None)
    else:
        selected = and_(
            Measurement.received_at <= cutoff,
            or_(Measurement.superseded_at.is_(None), Measurement.superseded_at > cutoff),
        )
        untrusted = or_(Measurement.trusted_at.is_(None), Measurement.trusted_at > cutoff)
    return selected, or_(unreliable, untrusted)


async def samples_for_hours(
    session: AsyncSession, node_id: int, start: datetime, end: datetime, cutoff: datetime | None
) -> list[Row]:
    """Số đo của node có measured_at trong (start, end], chọn theo `as_of_filter(cutoff)`, cũ → mới.

    Mỗi dòng có cột `excluded` cho biết mẫu bị loại khỏi giá trị trung bình.
    """
    selected, excluded = as_of_filter(cutoff)
    stmt = (
        select(
            Measurement.measured_at,
            Measurement.received_at,
            Measurement.max_age_s,
            Measurement.qc_flags,
            excluded.label("excluded"),
            Measurement.pm25,
            Measurement.pm10,
            Measurement.temperature,
            Measurement.humidity,
            Measurement.co2,
            Measurement.tvoc,
        )
        .where(
            Measurement.node_id == node_id, Measurement.measured_at > start, Measurement.measured_at <= end, selected
        )
        .order_by(Measurement.measured_at, Measurement.id)
    )
    return list((await session.execute(stmt)).all())


async def nodes_with_samples(session: AsyncSession, start: datetime, end: datetime) -> list[int]:
    """Node có số đo còn hiệu lực (kể cả bản bị loại) với measured_at trong (start, end]."""
    stmt = (
        select(Measurement.node_id)
        .where(Measurement.measured_at > start, Measurement.measured_at <= end, Measurement.superseded_at.is_(None))
        .distinct()
    )
    return list((await session.scalars(stmt)).all())
