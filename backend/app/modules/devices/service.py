"""Nghiệp vụ thiết bị: provisioning, tra/tạo node từ batch, trạng thái Gateway/node/cảm biến.

Mọi hàm nhận `session` của transaction đang chạy; không tự commit (backend_modules 1).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from geoalchemy2 import WKTElement
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings_store
from app.core.locks import address_key, node_address_locks
from app.modules.devices import addressing, repository
from app.modules.devices.models import Gateway, Node, NodeSensor

# Lý do từ chối bản ghi (ghi vào thống kê ingest)
REJECT_BAD_NODE_ID = "bad_node_id"
REJECT_RETIRED_ADDRESS = "retired_address"


class UnknownGatewayError(Exception):
    """Provisioning node với gateway_id không tồn tại hoặc đã ngưng."""


class NoFreeAddressError(Exception):
    """Mạng LoRa đã dùng hết 255 địa chỉ (gồm cả địa chỉ đang cách ly)."""


# ---------- provisioning (backend_design 6.8) ----------


async def provision_gateway(session: AsyncSession, name: str, location_desc: str | None) -> Gateway:
    """Đăng ký Gateway mới: mã GW_%03d kế tiếp, mạng 'default', trạng thái pending chờ Admin duyệt."""
    network = await repository.lock_default_network(session)
    gateway = Gateway(
        id=addressing.next_gateway_code(await repository.gateway_ids(session)),
        lora_network_id=network.id,
        name=name,
        location_desc=location_desc,
        registered_via="provision",
    )
    session.add(gateway)
    await session.flush()
    await session.refresh(gateway)
    return gateway


async def provision_node(
    session: AsyncSession, name: str, gateway_id: str | None, lat: float | None, lng: float | None, now: datetime
) -> Node:
    """Đăng ký node mới trong mạng của Gateway đã chọn: cấp địa chỉ nhỏ nhất còn trống, mã trạm mới, pending."""
    home: Gateway | None = None
    if gateway_id:
        home = await repository.get_gateway(session, gateway_id)
        if home is None or home.status in ("disabled", "retired"):
            raise UnknownGatewayError(gateway_id)
    network_id = home.lora_network_id if home else await repository.default_network_id(session)

    await repository.lock_network(session, network_id)  # hai lần provisioning không nhận cùng địa chỉ
    since = now - timedelta(days=await settings_store.get("address_quarantine_days"))
    taken = await repository.live_addrs(session, network_id) | await repository.quarantined_addrs(
        session, network_id, since
    )
    free = addressing.free_addresses(taken)
    if not free:
        raise NoFreeAddressError(network_id)

    # Ingest tự tạo node khóa theo địa chỉ; khóa cùng địa chỉ rồi kiểm tra lại để không tạo trùng
    for addr in free:
        await node_address_locks(session, [address_key(network_id, addr)])
        if not await repository.live_nodes(session, network_id, [addr]):
            break
    else:
        raise NoFreeAddressError(network_id)

    geom = WKTElement(f"POINT({lng} {lat})", srid=4326) if lat is not None and lng is not None else None
    return await _new_node(session, network_id, addr, name, "provision", home.id if home else None, geom)


async def list_nodes(session: AsyncSession) -> list[Node]:
    """Mọi node chưa ngưng hoạt động (kể cả pending), theo id."""
    return await repository.list_nodes(session)


async def get_node(session: AsyncSession, node_id: int) -> Node | None:
    """Node theo id nội bộ, hoặc None."""
    return await repository.get_node(session, node_id)


async def get_gateway(session: AsyncSession, gateway_id: str) -> Gateway | None:
    """Gateway theo mã, hoặc None."""
    return await repository.get_gateway(session, gateway_id)


async def list_active_gateways(session: AsyncSession) -> list[Gateway]:
    """Gateway đang active (chỉ những Gateway này hiện ở cổng cấu hình node, mục 14.1)."""
    return await repository.active_gateways(session)


# ---------- dùng khi ingest (backend_design 6.3, 6.4.1) ----------


async def get_or_create_gateway(session: AsyncSession, gateway_id: str) -> tuple[Gateway, bool]:
    """Khóa dòng Gateway; chưa có thì tự tạo pending/auto_discovered. Trả (gateway, vừa_tạo)."""
    created = False
    gateway = await repository.get_gateway(session, gateway_id, for_update=True)
    if gateway is None:
        network_id = await repository.default_network_id(session)
        created = await repository.insert_gateway_if_absent(session, gateway_id, network_id, "auto_discovered")
        gateway = await repository.get_gateway(session, gateway_id, for_update=True)
    return gateway, created


async def resolve_nodes(
    session: AsyncSession, gateway: Gateway, addrs: list[int], now: datetime
) -> tuple[dict[int, Node | str], list[Node]]:
    """Tra node theo địa chỉ trong mạng của Gateway (gọi sau khi đã khóa các địa chỉ).

    Trả ({địa chỉ: Node hoặc lý do từ chối}, danh sách node vừa tự tạo).
    Địa chỉ của node retired còn trong thời gian cách ly → từ chối; còn lại chưa có node → tạo node pending.
    """
    network_id = gateway.lora_network_id
    found: dict[int, Node | str] = dict(await repository.live_nodes(session, network_id, addrs))
    missing = [a for a in addrs if a not in found]
    created: list[Node] = []
    if missing:
        since = now - timedelta(days=await settings_store.get("address_quarantine_days"))
        quarantined = await repository.quarantined_addrs(session, network_id, since)
        for addr in missing:
            if addr in quarantined:
                found[addr] = REJECT_RETIRED_ADDRESS
            else:
                node = await _new_node(
                    session, network_id, addr, addressing.device_code(addr), "auto_discovered", gateway.id
                )
                found[addr] = node
                created.append(node)
    return found, created


def effective_interval(node: Node) -> int | None:
    """Chu kỳ hiệu lực của node (R24): khóa → expected; không khóa → observed, thiếu thì expected; không có → None."""
    if node.interval_locked:
        return node.expected_interval_s
    return node.observed_interval_s or node.expected_interval_s


async def min_interval_of_gateway(session: AsyncSession, gateway_id: str, now: datetime) -> int | None:
    """c_min: chu kỳ hiệu lực nhỏ nhất của các node Gateway đã chuyển tiếp trong 24 giờ qua."""
    return await repository.min_effective_interval(session, gateway_id, now - timedelta(hours=24))


async def record_link(session: AsyncSession, node_id: int, gateway_id: str, at: datetime, packets: int) -> None:
    """Ghi Gateway đã chuyển tiếp gói cho node (truy vết, kể cả bản trùng/không tin cậy)."""
    await repository.upsert_link(session, node_id, gateway_id, at, packets)


@dataclass
class NodeObservation:
    """Thông tin một batch đem lại cho node, đã lọc theo quy tắc bản ghi đáng tin (mục 6.4.1)."""

    gateway_id: str
    heard_at: datetime | None = None  # mọi bản ghi qua Gateway active, kể cả TIME_UNRELIABLE
    seen_at: datetime | None = None  # bản ghi đáng tin mới nhất (gồm heartbeat node)
    measurement_at: datetime | None = None  # số đo đáng tin mới nhất (không gồm heartbeat)
    battery_pct: int | None = None  # của bản ghi đáng tin mới nhất
    msg_id: int | None = None  # của bản ghi đáng tin mới nhất
    data_received_at: datetime | None = None  # có số đo được lưu (để đặt first_data_at)


def apply_node_observation(node: Node, obs: NodeObservation) -> None:
    """Cập nhật trạng thái node, chỉ khi thông tin mới hơn giá trị đang có (dữ liệu cũ gửi lại không ghi đè)."""
    if obs.heard_at and (node.last_heard_at is None or obs.heard_at > node.last_heard_at):
        node.last_heard_at = obs.heard_at
    if obs.seen_at and (node.last_seen_at is None or obs.seen_at >= node.last_seen_at):
        node.last_seen_at = obs.seen_at
        node.connectivity = "online"
        node.last_gateway_id = obs.gateway_id
        if obs.battery_pct is not None:
            node.battery_pct = obs.battery_pct
        if obs.msg_id is not None:
            node.last_msg_id = obs.msg_id
    if obs.measurement_at and (node.last_measurement_at is None or obs.measurement_at > node.last_measurement_at):
        node.last_measurement_at = obs.measurement_at
    if obs.data_received_at and node.first_data_at is None:
        node.first_data_at = obs.data_received_at


async def update_sensor_health(session: AsyncSession, node_id: int, sensor: str, health: str, at: datetime) -> None:
    """Ghi trạng thái một cảm biến từ số đo đáng tin: ok / warming_up / error, đếm số lần lỗi liên tiếp."""
    row = await repository.get_sensor(session, node_id, sensor)
    if row is None:
        row = NodeSensor(node_id=node_id, sensor=sensor, error_streak=0)
        session.add(row)
    row.health = health
    if health == "ok":
        row.last_ok_at, row.error_streak = at, 0
    elif health == "error":
        row.last_error_at, row.error_streak = at, (row.error_streak or 0) + 1


async def set_interval_stats(
    session: AsyncSession, node_id: int, observed_s: int | None, iqr_ratio: float | None, lost_packets: int | None
) -> None:
    """Ghi chu kỳ đo được (NULL khi chưa đủ hoặc không ổn định), độ phân tán và số gói LoRa mất trong 24 giờ."""
    node = await session.get(Node, node_id)
    if node is not None:
        node.observed_interval_s = observed_s
        node.observed_interval_iqr_ratio = iqr_ratio
        node.lost_packets_24h = lost_packets


async def gateway_exists(session: AsyncSession, gateway_id: str) -> bool:
    """Gateway đã có trong DB chưa (để chọn giới hạn tần suất theo Gateway hay theo IP)."""
    return await repository.get_gateway(session, gateway_id) is not None


async def mark_telemetry_rejected(session: AsyncSession, gateway_id: str, at: datetime) -> None:
    """Server vừa trả lỗi (413/429/503) cho telemetry có secret đúng: batch kế tiếp sẽ bị coi là nghi cũ."""
    gateway = await repository.get_gateway(session, gateway_id, for_update=True)
    if gateway is not None and gateway.telemetry_rejected_since is None:
        gateway.telemetry_rejected_since = at


def mark_telemetry_received(gateway: Gateway, at: datetime, has_msg_id: bool | None, stored_data: bool) -> None:
    """Gateway vừa được nhận một batch telemetry (200): xóa dấu bị từ chối, ghi lần nhận và bản firmware."""
    gateway.last_telemetry_at = at
    gateway.telemetry_rejected_since = None
    if has_msg_id is not None:
        gateway.sends_msg_id = has_msg_id
    if stored_data and gateway.first_data_at is None:
        gateway.first_data_at = at


def mark_gateway_seen(gateway: Gateway, at: datetime, ip: str | None) -> bool:
    """Gateway vừa gửi request có secret đúng: cập nhật lần cuối thấy, IP. Trả True nếu IP đổi so với lần trước."""
    ip_changed = bool(gateway.last_ip and ip and str(gateway.last_ip) != ip)
    gateway.last_seen_at = at
    gateway.connectivity = "online"
    if ip:
        gateway.last_ip = ip
    return ip_changed


async def _new_node(
    session: AsyncSession,
    network_id: int,
    addr: int,
    name: str,
    registered_via: str,
    home_gateway_id: str | None,
    geom: WKTElement | None = None,
) -> Node:
    """Tạo node pending với mã trạm mới (station_code không bao giờ tái sử dụng)."""
    node = Node(
        station_code=addressing.station_code(await repository.next_station_number(session)),
        lora_network_id=network_id,
        lora_addr=addr,
        name=name,
        registered_via=registered_via,
        home_gateway_id=home_gateway_id,
        geom=geom,
    )
    session.add(node)
    await session.flush()
    await session.refresh(node)
    return node
