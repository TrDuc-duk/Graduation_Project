"""Xử lý một batch telemetry trong MỘT transaction (backend_design 6.7).

Trình tự: khóa Gateway → khóa địa chỉ node tăng dần → xét batch nghi cũ → tra/tạo node → gán thời điểm đo
→ chống trùng theo thứ hạng → lưu số đo → cập nhật trạng thái (chỉ từ bản ghi đáng tin) → log, outbox, NOTIFY.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import groupby

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events, outbox, security_events, settings_store, timeutil
from app.core.db import run_in_transaction
from app.core.locks import address_key, node_address_locks
from app.modules.devices import service as devices
from app.modules.devices.models import Gateway, Node
from app.modules.hourly import service as hourly
from app.modules.ingest import dedup
from app.modules.ingest.normalize import Reading, normalize
from app.modules.ingest.schemas import TelemetryIn
from app.modules.ingest.staleness import check_stale
from app.modules.ingest.timing import TimeInput, assign_times, batch_max_age_s
from app.modules.telemetry import service as telemetry
from app.modules.telemetry.qc import QcFlag, is_state_trusted

REJECT_GATEWAY_INACTIVE = "gateway_inactive"
SETTING_KEYS = (
    "gateway_flush_interval_s",
    "gateway_heartbeat_interval_s",
    "stale_gap_factor",
    "stale_send_tolerance_s",
    "max_msg_gap",
    "pm_spike_delta",
)


@dataclass
class BatchResult:
    """Thống kê của một batch; accepted + duplicates + heartbeats + rejected = số bản ghi."""

    batch_id: int = 0
    accepted: int = 0
    duplicates: int = 0
    heartbeats: int = 0
    rejected: int = 0
    superseded: int = 0
    reject_reasons: Counter = field(default_factory=Counter)

    def response(self) -> dict:
        """Body 200 trả cho firmware (backend_design 6.2)."""
        return {
            "success": True,
            "accepted": self.accepted,
            "duplicates": self.duplicates,
            "heartbeats": self.heartbeats,
            "rejected": self.rejected,
        }


@dataclass
class BatchContext:
    """Thông tin dùng chung khi xử lý các node của một batch."""

    gateway: Gateway
    batch_id: int
    received_at: datetime
    stale: bool
    untrusted: bool  # Gateway chưa duyệt → cách ly
    max_age_s: int | None
    prev_last_telemetry_at: datetime | None
    settings: dict


async def ingest_telemetry(body: TelemetryIn, raw: dict, ip: str | None) -> BatchResult:
    """Nhận một batch telemetry: chạy trong transaction có thử lại (deadlock, lock timeout), trả thống kê."""
    received_at = timeutil.now()  # thời điểm nhận, không đổi giữa các lần thử lại
    settings = await settings_store.get_many(*SETTING_KEYS)
    attempts = 0

    async def work(session: AsyncSession) -> BatchResult:
        nonlocal attempts
        attempts += 1
        readings = [normalize(i, item) for i, item in enumerate(body.data)]  # mới mỗi lần thử
        return await _process_batch(session, body.gateway_id, raw, readings, received_at, ip, settings, attempts)

    return await run_in_transaction(work, lock_timeout="2s", statement_timeout="5s")


async def ingest_heartbeat(gateway_id: str, ip: str | None) -> None:
    """Heartbeat Gateway (5 phút/lần): chỉ cập nhật trạng thái kết nối của Gateway và ghi log."""
    received_at = timeutil.now()

    async def work(session: AsyncSession) -> None:
        gateway, created = await devices.get_or_create_gateway(session, gateway_id)
        await _gateway_contact_events(session, gateway, created, received_at, ip)
        gateway.last_heartbeat_at = received_at
        await telemetry.log_batch(
            session, received_at=received_at, kind="heartbeat", gateway_id=gateway.id, remote_ip=ip, http_status=200
        )

    await run_in_transaction(work, lock_timeout="2s", statement_timeout="5s")


async def _process_batch(
    session: AsyncSession,
    gateway_id: str,
    raw: dict,
    readings: list[Reading],
    received_at: datetime,
    ip: str | None,
    settings: dict,
    attempts: int,
) -> BatchResult:
    """Toàn bộ việc của một batch trong transaction đang mở."""
    started = timeutil.now()
    gateway, gateway_created = await devices.get_or_create_gateway(session, gateway_id)
    has_msg_id = any(r.msg_id is not None for r in readings) if readings else None
    result = BatchResult()
    result.batch_id = await telemetry.start_batch(
        session,
        received_at=received_at,
        kind="telemetry",
        gateway_id=gateway.id,
        remote_ip=ip,
        http_status=200,
        item_count=len(readings),
        has_msg_id=has_msg_id,
        payload=telemetry.strip_secrets(raw),
        attempts=attempts,
    )

    prev_last_seen_at, prev_last_telemetry_at = gateway.last_seen_at, gateway.last_telemetry_at
    await _gateway_contact_events(session, gateway, gateway_created, received_at, ip)

    if gateway.status in ("disabled", "retired"):  # Gateway đã ngưng: bỏ mọi bản ghi, vẫn trả 200
        result.rejected = len(readings)
        result.reject_reasons[REJECT_GATEWAY_INACTIVE] = len(readings)
        await _finish(session, result, received_at, started, stale_reason=None, possible_age_s=None)
        return result

    # Bản ghi node_id sai mẫu bị từ chối ngay; các địa chỉ còn lại được khóa theo thứ tự tăng dần (R10)
    valid = [r for r in readings if r.addr is not None]
    if len(valid) < len(readings):
        result.rejected += len(readings) - len(valid)
        result.reject_reasons[devices.REJECT_BAD_NODE_ID] += len(readings) - len(valid)
    network_id = gateway.lora_network_id
    await node_address_locks(session, [address_key(network_id, r.addr) for r in valid])

    c_min = await devices.min_interval_of_gateway(session, gateway.id, received_at)
    stale_reason = check_stale(
        received_at,
        prev_last_seen_at,
        gateway.telemetry_rejected_since,
        c_min,
        heartbeat_s=settings["gateway_heartbeat_interval_s"],
        flush_s=settings["gateway_flush_interval_s"],
        factor=settings["stale_gap_factor"],
        tolerance_s=settings["stale_send_tolerance_s"],
    )
    max_age_s = batch_max_age_s(
        received_at,
        stale_reason is not None,
        prev_last_seen_at,
        prev_last_telemetry_at,
        flush_s=settings["gateway_flush_interval_s"],
        tolerance_s=settings["stale_send_tolerance_s"],
    )
    ctx = BatchContext(
        gateway=gateway,
        batch_id=result.batch_id,
        received_at=received_at,
        stale=stale_reason is not None,
        untrusted=gateway.status == "pending",
        max_age_s=max_age_s,
        prev_last_telemetry_at=prev_last_telemetry_at,
        settings=settings,
    )

    nodes, created = await devices.resolve_nodes(session, gateway, sorted({r.addr for r in valid}), received_at)
    for node in created:
        await _node_discovered(session, node, gateway.id, ip)

    stored_any = False
    by_addr = groupby(sorted(valid, key=lambda r: (r.addr, r.seq)), key=lambda r: r.addr)
    for addr, group in by_addr:
        records = list(group)
        target = nodes[addr]
        if isinstance(target, str):  # địa chỉ đang cách ly sau khi node cũ ngưng hoạt động
            result.rejected += len(records)
            result.reject_reasons[target] += len(records)
            continue
        stored_any |= await _process_node(session, ctx, target, records, result)

    devices.mark_telemetry_received(gateway, received_at, has_msg_id, stored_any)
    possible_age_s = max_age_s if ctx.stale else None
    await _finish(session, result, received_at, started, stale_reason, possible_age_s)
    return result


async def _process_node(
    session: AsyncSession, ctx: BatchContext, node: Node, records: list[Reading], result: BatchResult
) -> bool:
    """Xử lý các bản ghi của một node trong batch. Trả True nếu có số đo được lưu."""
    interval = devices.effective_interval(node)
    times = assign_times(
        [TimeInput(r.msg_id, r.is_heartbeat) for r in records],
        ctx.received_at,
        interval,
        prev_last_telemetry_at=ctx.prev_last_telemetry_at,
        stale=ctx.stale,
        max_msg_gap=ctx.settings["max_msg_gap"],
        max_age_s=ctx.max_age_s,
    )
    base_flags = QcFlag.UNTRUSTED_GATEWAY if ctx.untrusted else QcFlag(0)
    for r, t in zip(records, times, strict=True):
        r.measured_at, r.time_source = t.measured_at, t.time_source
        r.flags |= t.flags | base_flags

    measurements = [r for r in records if not r.is_heartbeat]
    result.heartbeats += len(records) - len(measurements)
    await _mark_pm_spikes(session, node.id, measurements, ctx.settings["pm_spike_delta"])
    to_insert, superseded_keys = await _dedup(session, ctx, node.id, measurements, interval, result)

    ids = await telemetry.insert_measurements(session, [_measurement_row(ctx, node.id, r) for r in to_insert])
    if superseded_keys:
        await telemetry.mark_superseded(session, superseded_keys, ctx.received_at)
        result.superseded += len(superseded_keys)
    result.accepted += len(to_insert)
    # Bản mới hoặc bản bị thay rơi vào giờ đã đóng → tính lại giờ đó (backend_design 7); giờ đang mở do rollup lo
    changed_times = [r.measured_at for r in to_insert] + [measured_at for _, measured_at in superseded_keys]
    await hourly.enqueue_closed_hours(session, node.id, changed_times, ctx.received_at)

    await devices.record_link(session, node.id, ctx.gateway.id, ctx.received_at, len(records))
    inserted = {r.seq for r in to_insert}  # bản trùng không được lưu nên không tính là đáng tin
    trusted = [r for r in records if (r.is_heartbeat or r.seq in inserted) and is_state_trusted(r.flags)]
    await _update_node_state(session, ctx, node, records, trusted, stored=bool(to_insert))

    if ids or trusted:
        await outbox.publish(
            session,
            "measurements_ingested",
            {"batch_id": ctx.batch_id, "node_id": node.id, "measurement_ids": ids, "has_trusted": bool(trusted)},
            partition_key=f"node:{node.id}",
        )
    latest = max((r for r in trusted if not r.is_heartbeat), key=_newest_key, default=None)
    if latest is not None:  # SSE chỉ phát số đo đáng tin
        data = {"measured_at": latest.measured_at, "pm25": latest.pm25, "pm10": latest.pm10, "aqi": latest.aqi_instant}
        await events.notify(session, "measurement", data, node_id=node.id, station_code=node.station_code)
    return bool(to_insert)


async def _dedup(
    session: AsyncSession,
    ctx: BatchContext,
    node_id: int,
    measurements: list[Reading],
    interval: int | None,
    result: BatchResult,
) -> tuple[list[Reading], list[tuple[int, datetime]]]:
    """Chống trùng theo thứ hạng (6.5). Trả (bản ghi cần lưu, khóa (id, measured_at) của bản cũ bị thay)."""
    if not measurements:
        return [], []
    windows = {r.seq: dedup.window_s(r.msg_id is not None, interval) for r in measurements}
    since = ctx.received_at - timedelta(seconds=max(windows.values()))
    copies = await telemetry.find_matching_copies(session, node_id, [r.payload_hash for r in measurements], since)
    stored: dict[int, list] = defaultdict(list)  # hash → [(received_at, flags, khóa hoặc None nếu cùng batch)]
    for c in copies:
        stored[c.payload_hash].append((c.received_at, c.qc_flags, (c.id, c.measured_at)))

    to_insert: list[Reading] = []
    superseded: dict[tuple[int, datetime], None] = {}
    for r in measurements:
        window_start = ctx.received_at - timedelta(seconds=windows[r.seq])
        matches = [m for m in stored[r.payload_hash] if m[0] >= window_start]
        if matches and dedup.rank(r.flags) <= max(dedup.rank(m[1]) for m in matches):
            result.duplicates += 1
            continue
        for m in matches:  # bản mới hạng cao hơn mọi bản đã có → các bản đó bị thay
            if m[2] is not None:
                superseded[m[2]] = None
        stored[r.payload_hash] = [(ctx.received_at, r.flags, None)]
        to_insert.append(r)
    return to_insert, list(superseded)


async def _mark_pm_spikes(session: AsyncSession, node_id: int, measurements: list[Reading], delta: float) -> None:
    """Gắn PM_SPIKE khi PM2.5 tăng > delta so với mẫu đáng tin trước đó trong vòng 1 giờ (chỉ bản ghi đáng tin)."""
    trusted = [r for r in measurements if is_state_trusted(r.flags)]
    if not trusted:
        return
    first = min(r.measured_at for r in trusted)
    prev = await telemetry.last_trusted_pm25(session, node_id, first - timedelta(hours=1))
    for r in sorted(trusted, key=_newest_key):
        if r.pm25 is None:
            continue
        if prev is not None and r.pm25 - prev > delta:
            r.flags |= QcFlag.PM_SPIKE
        prev = r.pm25


async def _update_node_state(
    session: AsyncSession,
    ctx: BatchContext,
    node: Node,
    records: list[Reading],
    trusted: list[Reading],
    stored: bool,
) -> None:
    """Cập nhật trạng thái node và cảm biến theo quy tắc bản ghi đáng tin (mục 6.4.1)."""
    obs = devices.NodeObservation(gateway_id=ctx.gateway.id)
    if not ctx.untrusted:  # qua Gateway đã duyệt: nghe thấy node, kể cả khi batch nghi cũ
        obs.heard_at = ctx.received_at
    if stored:
        obs.data_received_at = ctx.received_at
    newest = max(trusted, key=_newest_key, default=None)
    if newest is not None:
        obs.seen_at, obs.battery_pct, obs.msg_id = newest.measured_at, newest.battery_pct, newest.msg_id
    newest_measurement = max((r for r in trusted if not r.is_heartbeat), key=_newest_key, default=None)
    if newest_measurement is not None:
        obs.measurement_at = newest_measurement.measured_at
        for sensor, health in newest_measurement.sensor_health.items():
            await devices.update_sensor_health(session, node.id, sensor, health, newest_measurement.measured_at)
    devices.apply_node_observation(node, obs)


def _newest_key(r: Reading) -> tuple:
    """Thứ tự thời gian của bản ghi: (measured_at, seq)."""
    return (r.measured_at, r.seq)


def _measurement_row(ctx: BatchContext, node_id: int, r: Reading) -> dict:
    """Dòng measurements từ một Reading đã gán thời điểm và cờ."""
    return {
        "node_id": node_id,
        "measured_at": r.measured_at,
        "received_at": ctx.received_at,
        "max_age_s": ctx.max_age_s,
        "trusted_at": None if ctx.untrusted else ctx.received_at,
        "gateway_id": ctx.gateway.id,
        "batch_id": ctx.batch_id,
        "seq": r.seq,
        "msg_id": r.msg_id,
        "time_source": r.time_source,
        "pm25": r.pm25,
        "pm10": r.pm10,
        "co2": r.co2,
        "tvoc": r.tvoc,
        "temperature": r.temperature,
        "humidity": r.humidity,
        "battery_pct": r.battery_pct,
        "aqi_instant": r.aqi_instant,
        "qc_flags": r.flags,
        "payload_hash": r.payload_hash,
    }


async def _gateway_contact_events(
    session: AsyncSession, gateway: Gateway, created: bool, at: datetime, ip: str | None
) -> None:
    """Ghi lần liên lạc của Gateway; Gateway mới tự tạo hoặc đổi IP thì ghi sự kiện bảo mật."""
    ip_changed = devices.mark_gateway_seen(gateway, at, ip)
    if created:
        await security_events.record(session, "device_discovered", "info", source_ip=ip, gateway_id=gateway.id)
        await events.notify(session, "device_discovered", {"kind": "gateway"}, gateway_id=gateway.id)
    if ip_changed:
        await security_events.record(session, "gateway_ip_changed", "info", source_ip=ip, gateway_id=gateway.id)


async def _node_discovered(session: AsyncSession, node: Node, gateway_id: str, ip: str | None) -> None:
    """Node lạ vừa được tự tạo (pending): ghi sự kiện để Admin duyệt."""
    await security_events.record(
        session, "device_discovered", "info", source_ip=ip, gateway_id=gateway_id, node_id=node.id
    )
    await events.notify(
        session, "device_discovered", {"kind": "node", "device_code": node.device_code}, node_id=node.id
    )


async def _finish(
    session: AsyncSession,
    result: BatchResult,
    received_at: datetime,
    started: datetime,
    stale_reason: str | None,
    possible_age_s: int | None,
) -> None:
    """Điền thống kê vào ingest_batches và phát sự kiện ingest_batch cho trang Admin."""
    reasons = dict(result.reject_reasons)
    await telemetry.finish_batch(
        session,
        result.batch_id,
        received_at,
        accepted=result.accepted,
        duplicates=result.duplicates,
        superseded=result.superseded,
        heartbeats=result.heartbeats,
        rejected=result.rejected,
        stale_suspected=stale_reason is not None,
        stale_reason=stale_reason,
        possible_age_s=possible_age_s,
        error=f"rejected: {reasons}" if reasons else None,
        processing_ms=int((timeutil.now() - started).total_seconds() * 1000),
    )
    await events.notify(session, "ingest_batch", {**result.response(), "batch_id": result.batch_id})
