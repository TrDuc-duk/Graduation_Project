"""Ghép dữ liệu node, Gateway, số đo cho dashboard demo. Chỉ đọc; không sở hữu bảng nào."""

from dataclasses import asdict
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings_store, timeutil
from app.modules.dev.schemas import UNITS, Freshness, GatewayOut, HourlyPoint, NodeOut, NodeReadings, Reading
from app.modules.devices import service as devices
from app.modules.devices.models import Gateway, Node
from app.modules.ingest.normalize import instant_aqi
from app.modules.stations import service as stations
from app.modules.telemetry import service as telemetry
from app.modules.telemetry.models import Measurement
from app.modules.telemetry.qc import QcFlag

MAX_POINTS = 20_000
HOURLY_RANGES = (168, 720)  # 7 và 30 ngày: trả trung bình theo giờ thay cho số đo thô


async def list_nodes(session: AsyncSession) -> list[NodeOut]:
    """Mọi node chưa ngưng hoạt động (kể cả pending) kèm vị trí, Gateway và độ mới dữ liệu."""
    now = timeutil.now()
    nodes = await devices.list_nodes(session)
    positions = await devices.node_positions(session, [n.id for n in nodes])
    return [await _node_out(session, node, now, position=positions.get(node.id)) for node in nodes]


async def node_readings(session: AsyncSession, node_id: int, hours: int) -> NodeReadings | None:
    """Dữ liệu của node trong `hours` giờ gần nhất (cũ → mới) và số đo mới nhất; node không có thì None.

    1, 6, 24 giờ: số đo thô. 168, 720 giờ: trung bình từng giờ, giờ không có số đo vẫn có điểm (giá trị null)
    để biểu đồ hiện khoảng đứt.
    """
    node = await devices.get_node(session, node_id)
    if node is None:
        return None
    now = timeutil.now()
    latest = await telemetry.latest_reading(session, node.id)
    position = (await devices.node_positions(session, [node.id])).get(node.id)
    if hours in HOURLY_RANGES:
        last_label = _ceil_hour(now)  # giờ đang chạy: cửa sổ (h−1, h] chứa now
        since = last_label - timedelta(hours=hours)
        hourly = _hourly_series(await telemetry.hourly_means(session, node.id, since), since, hours)
        rows: list[Measurement] = []
    else:
        since = now - timedelta(hours=hours)
        rows = await telemetry.readings(session, node.id, since, MAX_POINTS + 1)
        hourly = []
    return NodeReadings(
        node=await _node_out(session, node, now, latest, position),
        hours=hours,
        resolution="hour" if hours in HOURLY_RANGES else "raw",
        since=since,
        server_time=now,
        units=UNITS,
        latest=_reading(latest) if latest else None,
        readings=[_reading(m) for m in rows[-MAX_POINTS:]],
        hourly=hourly,
        truncated=len(rows) > MAX_POINTS,
    )


def _ceil_hour(t: datetime) -> datetime:
    """Làm tròn lên đầu giờ kế tiếp: 14:37 → 15:00; 14:00 giữ nguyên."""
    floor = timeutil.floor_hour(t)
    return floor if floor == t else floor + timedelta(hours=1)


def _hourly_series(rows: list, since: datetime, hours: int) -> list[HourlyPoint]:
    """Đủ `hours` điểm giờ liên tiếp sau `since`; giờ không có dòng trung bình thì giá trị null, 0 mẫu."""
    by_hour = {r.hour: r for r in rows}
    points = []
    for i in range(1, hours + 1):
        label = since + timedelta(hours=i)
        r = by_hour.get(label)
        points.append(
            HourlyPoint(
                time=label,
                n_samples=r.n_samples if r else 0,
                pm25=_round(r.pm25) if r else None,
                pm10=_round(r.pm10) if r else None,
                co2=_round(r.co2, 0) if r else None,
                tvoc=_round(r.tvoc, 0) if r else None,
                temperature=_round(r.temperature) if r else None,
                humidity=_round(r.humidity) if r else None,
                aqi=instant_aqi(r.pm25, r.pm10) if r else None,  # cùng công thức compute_aqi, từ PM trung bình giờ
            )
        )
    return points


def _round(value: float | None, digits: int = 1) -> float | None:
    """Làm tròn số đo hiển thị (backend_design 11.1: 1 chữ số); null giữ null."""
    return None if value is None else round(value, digits)


async def _node_out(
    session: AsyncSession,
    node: Node,
    now: datetime,
    latest: Measurement | None = None,
    position: tuple[float, float] | None = None,
) -> NodeOut:
    """Thông tin node: vị trí (nếu có), Gateway gần nhất (hoặc Gateway nhà), số đo mới nhất và độ mới dữ liệu."""
    latest = latest or await telemetry.latest_reading(session, node.id)
    gateway_id = (latest.gateway_id if latest else None) or node.last_gateway_id or node.home_gateway_id
    gateway = await devices.get_gateway(session, gateway_id) if gateway_id else None
    return NodeOut(
        id=node.id,
        station_code=node.station_code,
        device_code=node.device_code,
        name=node.name,
        district=node.district,
        latitude=position[0] if position else None,
        longitude=position[1] if position else None,
        status=node.status,
        connectivity=node.connectivity,
        battery_pct=node.battery_pct,
        effective_interval_s=devices.effective_interval(node),
        last_seen_at=node.last_seen_at,
        last_measurement_at=node.last_measurement_at,
        gateway=await _gateway_out(gateway, now) if gateway else None,
        freshness=Freshness(**asdict(await stations.freshness(node, latest, now))),
        latest=_reading(latest) if latest else None,
    )


async def _gateway_out(gateway: Gateway, now: datetime) -> GatewayOut:
    """Gateway kèm cờ online: có liên lạc trong gateway_offline_after_s (mặc định 15 phút)."""
    offline_after = await settings_store.get("gateway_offline_after_s")
    online = gateway.last_seen_at is not None and (now - gateway.last_seen_at).total_seconds() <= offline_after
    return GatewayOut(
        id=gateway.id,
        name=gateway.name,
        status=gateway.status,
        online=online,
        last_seen_at=gateway.last_seen_at,
        last_telemetry_at=gateway.last_telemetry_at,
    )


def _reading(m: Measurement) -> Reading:
    """Đổi một dòng measurements thành Reading, giữ nguyên null."""
    return Reading(
        measured_at=m.measured_at,
        received_at=m.received_at,
        gateway_id=m.gateway_id,
        time_source=m.time_source,
        pm25=m.pm25,
        pm10=m.pm10,
        co2=m.co2,
        tvoc=m.tvoc,
        temperature=m.temperature,
        humidity=m.humidity,
        battery_pct=m.battery_pct,
        aqi_instant=m.aqi_instant,
        qc_flags=m.qc_flags,
        quarantined=bool(m.qc_flags & QcFlag.UNTRUSTED_GATEWAY),
        time_unreliable=bool(m.qc_flags & QcFlag.TIME_UNRELIABLE),
    )
