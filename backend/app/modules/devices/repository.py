"""Truy vấn SQL của module devices. Không commit; transaction do service/người gọi quản lý."""

from datetime import datetime

from sqlalchemy import Row, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.devices.models import Gateway, LoraNetwork, Node, NodeGatewayLink, NodeSensor

DEFAULT_NETWORK = "default"


async def lock_default_network(session: AsyncSession) -> LoraNetwork:
    """Khóa dòng mạng 'default' tới hết transaction: các lần cấp mã Gateway/địa chỉ node chạy lần lượt."""
    stmt = select(LoraNetwork).where(LoraNetwork.code == DEFAULT_NETWORK).with_for_update()
    return (await session.scalars(stmt)).one()


async def default_network_id(session: AsyncSession) -> int:
    """ID của mạng LoRa 'default' (mọi Gateway hiện thuộc mạng này)."""
    return (await session.scalars(select(LoraNetwork.id).where(LoraNetwork.code == DEFAULT_NETWORK))).one()


async def lock_network(session: AsyncSession, network_id: int) -> None:
    """Khóa dòng một mạng LoRa tới hết transaction (dùng khi cấp địa chỉ node)."""
    await session.execute(select(LoraNetwork.id).where(LoraNetwork.id == network_id).with_for_update())


async def gateway_ids(session: AsyncSession) -> list[str]:
    """Mọi mã Gateway đang có (để sinh mã kế tiếp)."""
    return list((await session.scalars(select(Gateway.id))).all())


async def list_nodes(session: AsyncSession) -> list[Node]:
    """Mọi node chưa ngưng hoạt động, theo id."""
    return list((await session.scalars(select(Node).where(Node.status != "retired").order_by(Node.id))).all())


async def list_public_nodes(session: AsyncSession) -> list[Node]:
    """Trạm công khai: node đã duyệt (`active`) và bật `is_public`, theo mã trạm."""
    stmt = select(Node).where(Node.status == "active", Node.is_public.is_(True)).order_by(Node.station_code)
    return list((await session.scalars(stmt)).all())


async def node_positions(session: AsyncSession, node_ids: list[int]) -> dict[int, tuple[float, float]]:
    """Tọa độ (vĩ độ, kinh độ) của các node đã có vị trí; node chưa có tọa độ không nằm trong kết quả."""
    if not node_ids:
        return {}
    stmt = select(Node.id, func.ST_Y(Node.geom), func.ST_X(Node.geom)).where(
        Node.id.in_(node_ids), Node.geom.is_not(None)
    )
    return {node_id: (lat, lng) for node_id, lat, lng in (await session.execute(stmt)).all()}


async def forecast_nodes(session: AsyncSession) -> list[Node]:
    """Node được dự báo: đang `active` và bật `forecast_enabled` (backend_design 8.4), theo id."""
    stmt = select(Node).where(Node.status == "active", Node.forecast_enabled.is_(True)).order_by(Node.id)
    return list((await session.scalars(stmt)).all())


async def public_points(session: AsyncSession) -> list[Row]:
    """Trạm công khai có tọa độ (active, is_public, geom khác NULL): (Node, lat, lng, geometry GeoJSON)."""
    stmt = (
        select(
            Node,
            func.ST_Y(Node.geom).label("lat"),
            func.ST_X(Node.geom).label("lng"),
            func.ST_AsGeoJSON(Node.geom).label("geojson"),
        )
        .where(Node.status == "active", Node.is_public.is_(True), Node.geom.is_not(None))
        .order_by(Node.station_code)
    )
    return list((await session.execute(stmt)).all())


async def nearest_public(session: AsyncSession, lat: float, lng: float, limit: int) -> list[Row]:
    """Trạm công khai có tọa độ gần điểm (lat, lng) nhất: (Node, lat, lng, distance_m).

    Sắp xếp và khoảng cách cùng một công thức `ST_Distance` trên geography (mét), không dùng `<->` trên geometry 4326
    vì nó xếp theo độ (backend_design 3.2, R35).
    """
    point = func.ST_SetSRID(func.ST_MakePoint(lng, lat), 4326)
    distance = func.ST_Distance(func.Geography(Node.geom), func.Geography(point))
    stmt = (
        select(Node, func.ST_Y(Node.geom).label("lat"), func.ST_X(Node.geom).label("lng"), distance.label("distance_m"))
        .where(Node.status == "active", Node.is_public.is_(True), Node.geom.is_not(None))
        .order_by(distance, Node.station_code)
        .limit(limit)
    )
    return list((await session.execute(stmt)).all())


async def get_node(session: AsyncSession, node_id: int) -> Node | None:
    """Đọc một node theo id nội bộ."""
    return await session.get(Node, node_id)


async def get_gateway(session: AsyncSession, gateway_id: str, *, for_update: bool = False) -> Gateway | None:
    """Đọc một Gateway theo mã; for_update=True thì khóa dòng tới hết transaction."""
    stmt = select(Gateway).where(Gateway.id == gateway_id)
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.scalars(stmt)).one_or_none()


async def insert_gateway_if_absent(
    session: AsyncSession, gateway_id: str, network_id: int, registered_via: str
) -> bool:
    """Tạo Gateway pending nếu chưa có (an toàn khi hai request cùng tạo); trả True nếu vừa tạo."""
    stmt = (
        insert(Gateway)
        .values(id=gateway_id, lora_network_id=network_id, name=gateway_id, registered_via=registered_via)
        .on_conflict_do_nothing(index_elements=["id"])
        .returning(Gateway.id)
    )
    return (await session.scalar(stmt)) is not None


async def active_gateways(session: AsyncSession) -> list[Gateway]:
    """Gateway đang active, theo mã (danh sách cho cổng cấu hình của node)."""
    return list((await session.scalars(select(Gateway).where(Gateway.status == "active").order_by(Gateway.id))).all())


async def live_nodes(session: AsyncSession, network_id: int, addrs: list[int]) -> dict[int, Node]:
    """Node chưa retired đang giữ các địa chỉ trong mạng: {địa chỉ: Node}."""
    stmt = select(Node).where(Node.lora_network_id == network_id, Node.lora_addr.in_(addrs), Node.status != "retired")
    return {n.lora_addr: n for n in (await session.scalars(stmt)).all()}


async def quarantined_addrs(session: AsyncSession, network_id: int, since: datetime) -> set[int]:
    """Địa chỉ của node retired sau `since` (còn trong thời gian cách ly, chưa được cấp lại)."""
    stmt = select(Node.lora_addr).where(
        Node.lora_network_id == network_id, Node.status == "retired", Node.retired_at >= since
    )
    return set((await session.scalars(stmt)).all())


async def live_addrs(session: AsyncSession, network_id: int) -> set[int]:
    """Địa chỉ đang thuộc node chưa retired trong mạng."""
    stmt = select(Node.lora_addr).where(Node.lora_network_id == network_id, Node.status != "retired")
    return set((await session.scalars(stmt)).all())


async def next_station_number(session: AsyncSession) -> int:
    """Lấy số kế tiếp của station_code_seq (không bao giờ lặp lại)."""
    return await session.scalar(text("SELECT nextval('station_code_seq')"))


async def min_effective_interval(session: AsyncSession, gateway_id: str, since: datetime) -> int | None:
    """c_min: chu kỳ hiệu lực nhỏ nhất của các node mà Gateway chuyển tiếp từ `since` (backend_design 6.6.3).

    Chu kỳ hiệu lực theo R24: khóa → expected; không khóa → observed, thiếu thì expected.
    """
    stmt = text("""
        SELECT min(CASE WHEN n.interval_locked THEN n.expected_interval_s
                        ELSE coalesce(n.observed_interval_s, n.expected_interval_s) END)
        FROM node_gateway_links l JOIN nodes n ON n.id = l.node_id
        WHERE l.gateway_id = :gw AND l.last_seen_at >= :since
    """)
    return await session.scalar(stmt, {"gw": gateway_id, "since": since})


async def upsert_link(session: AsyncSession, node_id: int, gateway_id: str, at: datetime, packets: int) -> None:
    """Ghi nhận Gateway vừa chuyển tiếp `packets` gói của node."""
    stmt = insert(NodeGatewayLink).values(
        node_id=node_id, gateway_id=gateway_id, first_seen_at=at, last_seen_at=at, packet_count=packets
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["node_id", "gateway_id"],
        set_={
            "last_seen_at": func.greatest(NodeGatewayLink.last_seen_at, at),
            "packet_count": NodeGatewayLink.packet_count + packets,
        },
    )
    await session.execute(stmt)


async def get_sensor(session: AsyncSession, node_id: int, sensor: str) -> NodeSensor | None:
    """Đọc trạng thái một cảm biến của node."""
    return await session.get(NodeSensor, (node_id, sensor))
