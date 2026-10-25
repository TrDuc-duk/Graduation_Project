"""Giao diện của module hourly: tính dữ liệu giờ từ số đo thô và tra chuỗi giờ/ngày (backend_design 7, 11.4)."""

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events, outbox, settings_store
from app.core.aqi_scale import level_of
from app.core.db import run_in_transaction
from app.core.locks import address_key, node_address_locks
from app.modules.devices import service as devices
from app.modules.devices.models import Node
from app.modules.hourly import repository
from app.modules.hourly.aggregate import (
    HOUR,
    HourAggregate,
    Sample,
    aggregate,
    aqi_from_pm,
    empty_hour,
    hour_label,
)
from app.modules.hourly.models import NodeHourly
from app.modules.telemetry import service as telemetry


@dataclass(frozen=True)
class DayPoint:
    """Một ngày (giờ Việt Nam): trung bình các giờ có dữ liệu, AQI ngày = compute_aqi của PM trung bình ngày."""

    day: date
    n_hours: int
    aqi: int | None
    pm25: float | None
    pm10: float | None
    temperature: float | None
    humidity: float | None
    co2: float | None
    tvoc: float | None


@dataclass(frozen=True)
class ProfilePoint:
    """AQI giờ trung bình tại một giờ trong ngày (0–23, giờ Việt Nam của nhãn h)."""

    hour_of_day: int
    aqi: float
    n_hours: int


async def compute_hours(
    session: AsyncSession, node: Node, first: datetime, last: datetime, cutoff: datetime | None = None
) -> dict[datetime, HourAggregate]:
    """Tính (không ghi) các giờ có nhãn từ `first` tới `last` của node; `cutoff` = theo trạng thái lúc đó.

    Dùng chung cho đóng giờ, tính lại và as-of nên mọi nơi ra cùng con số.
    """
    rows = await telemetry.samples_for_hours(session, node.id, first - HOUR, last, cutoff)
    samples = [Sample(**r._mapping) for r in rows]
    min_samples = await settings_store.get("hourly_min_samples")
    return aggregate(samples, devices.effective_interval(node), min_samples)


async def hourly_as_of(
    session: AsyncSession, node_id: int, first: datetime, last: datetime, cutoff: datetime
) -> list[HourAggregate]:
    """Dữ liệu giờ như lẽ ra tính được tại `cutoff` (R21): chỉ bản ghi đã nhận, đã được tin cậy và còn hiệu lực
    vào lúc đó. Dùng cho dự báo chạy bù, backtest, test không rò rỉ. Giờ trống không có phần tử.
    """
    node = await devices.get_node(session, node_id)
    if node is None:
        return []
    return list((await compute_hours(session, node, first, last, cutoff)).values())


async def latest_closed_hour(session: AsyncSession, node_id: int, since: datetime) -> NodeHourly | None:
    """Giờ đã đóng mới nhất của node có nhãn sau `since` (AQI giờ hiện hành); không có thì None."""
    return await repository.latest_closed(session, node_id, since)


async def series_hour(session: AsyncSession, node_id: int, start: datetime, end: datetime) -> list[NodeHourly]:
    """Các dòng giờ đã lưu có nhãn trong (start, end], cũ → mới (gồm cả giờ đang mở, chỉ để hiển thị)."""
    return await repository.get_hours(session, node_id, start, end)


async def series_day(session: AsyncSession, node_id: int, start: datetime, end: datetime) -> list[DayPoint]:
    """Chuỗi theo ngày từ các giờ có nhãn trong (start, end]."""
    return [
        DayPoint(
            day=r.day,
            n_hours=r.n_hours,
            aqi=aqi_from_pm(r.pm25, r.pm10),
            pm25=r.pm25,
            pm10=r.pm10,
            temperature=r.temperature,
            humidity=r.humidity,
            co2=r.co2,
            tvoc=r.tvoc,
        )
        for r in await repository.day_means(session, node_id, start, end)
    ]


async def profile(session: AsyncSession, node_id: int, since: datetime) -> list[ProfilePoint]:
    """Chu kỳ ngày: AQI giờ trung bình theo giờ trong ngày, từ các giờ đã đóng sau `since` (chỉ giờ có dữ liệu)."""
    rows = await repository.aqi_by_hour_of_day(session, node_id, since)
    return [ProfilePoint(hour_of_day=r.hour_of_day, aqi=r.aqi, n_hours=r.n_hours) for r in rows]


# ---------- ghi dữ liệu giờ: đóng giờ, giờ đang mở, tính lại ----------


async def close_hour(hour_end: datetime, now: datetime) -> dict:
    """Bước 1 của đường ống giờ (backend_design 7.1): tính và đóng giờ `hour_end` cho mọi node có dữ liệu.

    Mỗi node một transaction ngắn để không giữ khóa node lâu (ingest chỉ chờ khóa 2 giây).
    Dòng đã đóng không bị ghi lại (chạy lại không đổi gì); dữ liệu muộn của giờ đã đóng đi qua hàng đợi tính lại.
    """
    closed = 0
    for node_id in await run_in_transaction(lambda s: _node_ids_of_hour(s, hour_end)):
        if await run_in_transaction(lambda s, n=node_id: _write_hour(s, n, hour_end, now, close=True)):
            closed += 1
    return {"hour_end": hour_end.isoformat(), "closed": closed}


async def rollup_open_hours(now: datetime) -> dict:
    """Tính các giờ chưa đóng (giờ hiện tại, và giờ trước nếu chưa qua mốc đóng) để hiển thị; không đổi revision."""
    current = hour_label(now)
    hours = [current]
    if not await is_closable(current - HOUR, now):
        hours.insert(0, current - HOUR)
    written = 0
    for hour_end in hours:
        for node_id in await run_in_transaction(lambda s, h=hour_end: _node_ids_of_hour(s, h)):
            if await run_in_transaction(lambda s, n=node_id, h=hour_end: _write_hour(s, n, h, now, close=False)):
                written += 1
    return {"open_hours": [h.isoformat() for h in hours], "written": written}


async def _write_hour(session: AsyncSession, node_id: int, hour_end: datetime, now: datetime, *, close: bool) -> bool:
    """Tính một giờ của một node rồi ghi dòng đã đóng (`close`) hoặc đang mở; bỏ qua dòng đã đóng.

    Trả True nếu có ghi dòng. Giờ không còn mẫu nào thì xóa dòng chưa đóng.
    """
    node = await devices.get_node(session, node_id)
    if node is None:
        return False
    await _lock(session, [node])
    row = await repository.get_hour(session, node_id, hour_end)
    if row is not None and row.is_closed:
        return False
    if close:
        await repository.dequeue(session, node_id, hour_end)  # đóng lần đầu đã tính từ dữ liệu hiện tại
    agg = (await compute_hours(session, node, hour_end, hour_end)).get(hour_end)
    if agg is None:
        if row is not None:
            await repository.delete_hour(session, node_id, hour_end)
        return False
    await repository.upsert_hour(session, node_id, agg, is_closed=close, revision=0, at=now)
    if close:
        await _notify_hourly(session, node, agg)
    return True


async def is_closable(hour_end: datetime, now: datetime) -> bool:
    """Giờ `h` được đóng khi now ≥ h + hour_close_grace_s (chờ Gateway xả buffer, backend_design 7)."""
    grace = await settings_store.get("hour_close_grace_s")
    return now >= hour_end + timedelta(seconds=grace)


async def enqueue_recompute(session: AsyncSession, node_id: int, hour_end: datetime) -> None:
    """Xếp hàng tính lại một giờ của node (dữ liệu muộn, bản bị thay, Gateway được duyệt)."""
    await repository.enqueue(session, node_id, hour_end)


async def enqueue_closed_hours(session: AsyncSession, node_id: int, times: list[datetime], now: datetime) -> int:
    """Xếp hàng tính lại các giờ đã qua mốc đóng chứa các thời điểm đo `times`; giờ đang mở do rollup lo.

    Trả số giờ đã xếp hàng.
    """
    hours = {hour_label(t) for t in times}
    queued = 0
    for hour_end in sorted(hours):
        if await is_closable(hour_end, now):
            await repository.enqueue(session, node_id, hour_end)
            queued += 1
    return queued


async def process_recompute_queue(now: datetime, limit: int = 100) -> dict:
    """Tính lại các giờ trong hàng đợi đã qua mốc đóng; mỗi mục một transaction (backend_design 7).

    Giờ đổi kết quả thì `revision += 1` và ghi outbox `hourly_revised` trong cùng transaction.
    """
    grace = await settings_store.get("hour_close_grace_s")
    entries = await run_in_transaction(lambda s: repository.queued(s, now - timedelta(seconds=grace), limit))
    revised = 0
    for e in entries:
        if await run_in_transaction(lambda s, e=e: _recompute(s, e.node_id, e.hour_end, now)):
            revised += 1
    return {"processed": len(entries), "revised": revised}


async def _recompute(session: AsyncSession, node_id: int, hour_end: datetime, now: datetime) -> bool:
    """Tính lại một giờ đã qua mốc đóng; True nếu kết quả đổi (đã ghi revision mới và outbox)."""
    node = await devices.get_node(session, node_id)
    if node is None:
        await repository.dequeue(session, node_id, hour_end)
        return False
    await _lock(session, [node])
    await repository.dequeue(session, node_id, hour_end)
    row = await repository.get_hour(session, node_id, hour_end)
    if row is not None and not row.is_closed:
        return False  # giờ chưa được đường ống đóng: close_hour sẽ tính từ dữ liệu mới nhất
    agg = (await compute_hours(session, node, hour_end, hour_end)).get(hour_end)
    if agg is None:
        if row is None:
            return False
        agg = empty_hour(hour_end, devices.effective_interval(node))
    if row is not None and _same(row, agg):
        return False
    revision = 0 if row is None else row.revision + 1
    await repository.upsert_hour(session, node_id, agg, is_closed=True, revision=revision, at=now)
    await _notify_hourly(session, node, agg)
    await outbox.publish(
        session,
        "hourly_revised",
        {"node_id": node_id, "hour_end": hour_end.isoformat(), "revision": revision},
        partition_key=f"node:{node_id}",
    )
    return True


async def _notify_hourly(session: AsyncSession, node: Node, agg: HourAggregate) -> None:
    """SSE `hourly {hour_end, aqi, level}` của giờ vừa đóng/tính lại; gửi sau commit (NOTIFY trong transaction)."""
    level = level_of(agg.aqi)
    data = {"hour_end": agg.hour_end.isoformat(), "aqi": agg.aqi, "level": level.key if level else None}
    await events.notify(session, "hourly", data, node_id=node.id, station_code=node.station_code)


async def _node_ids_of_hour(session: AsyncSession, hour_end: datetime) -> list[int]:
    """Node có số đo hoặc đã có dòng ở giờ `hour_end`, theo id tăng dần."""
    ids = set(await telemetry.nodes_with_samples(session, hour_end - HOUR, hour_end))
    ids |= set(await repository.nodes_with_rows(session, hour_end))
    return sorted(ids)


async def _lock(session: AsyncSession, nodes: list[Node]) -> None:
    """Khóa địa chỉ của node (cùng khóa ingest dùng, R10): ghi giờ và ingest của một node không chạy chồng,
    nên kết quả tính luôn thấy dữ liệu đã commit mới nhất.
    """
    await node_address_locks(session, [address_key(n.lora_network_id, n.lora_addr) for n in nodes])


def _same(row: NodeHourly, agg: HourAggregate) -> bool:
    """Dòng đã lưu có cùng kết quả với lần tính mới không (coverage là real nên so gần đúng)."""
    for key, value in asdict(agg).items():
        stored = getattr(row, key)
        if key == "coverage" and stored is not None and value is not None:
            if abs(stored - value) > 1e-6:
                return False
        elif stored != value:
            return False
    return True
