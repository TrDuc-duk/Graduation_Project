"""Model SQLAlchemy của module devices (bảng ở database_design 5.2). Chỉ module devices dùng trực tiếp."""

from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import BigInteger, Computed, FetchedValue, ForeignKey, Identity, Integer, SmallInteger, Text
from sqlalchemy.dialects.postgresql import INET, REAL
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# Cột có giá trị mặc định/trigger phía DB: ORM không gửi khi INSERT, đọc lại sau khi ghi
DB_DEFAULT = {"server_default": FetchedValue()}


class LoraNetwork(Base):
    """Không gian địa chỉ LoRa 1–255 của node (P15). Hiện chỉ có mạng 'default'."""

    __tablename__ = "lora_networks"

    id: Mapped[int] = mapped_column(SmallInteger, Identity(always=True), primary_key=True)
    code: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)


class Gateway(Base):
    """Gateway LoRa → HTTP. `id` là mã firmware (GW_001)."""

    __tablename__ = "gateways"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    lora_network_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("lora_networks.id"))
    name: Mapped[str] = mapped_column(Text)
    location_desc: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, **DB_DEFAULT)
    registered_via: Mapped[str] = mapped_column(Text)
    connectivity: Mapped[str] = mapped_column(Text, **DB_DEFAULT)
    sends_msg_id: Mapped[bool | None]
    last_seen_at: Mapped[datetime | None]
    last_heartbeat_at: Mapped[datetime | None]
    last_telemetry_at: Mapped[datetime | None]
    telemetry_rejected_since: Mapped[datetime | None]
    last_ip: Mapped[str | None] = mapped_column(INET)
    approved_at: Mapped[datetime | None]
    first_data_at: Mapped[datetime | None]
    retired_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(**DB_DEFAULT)


class Node(Base):
    """Node cảm biến = trạm. `id` nội bộ; firmware gọi bằng `device_code` (NODE_007) trong một mạng LoRa."""

    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(Integer, Identity(always=True), primary_key=True)
    station_code: Mapped[str] = mapped_column(Text)
    lora_network_id: Mapped[int] = mapped_column(SmallInteger, ForeignKey("lora_networks.id"))
    lora_addr: Mapped[int] = mapped_column(SmallInteger)
    device_code: Mapped[str] = mapped_column(Text, Computed("'NODE_' || lpad(lora_addr::text, 3, '0')"))
    name: Mapped[str] = mapped_column(Text)
    district: Mapped[str | None] = mapped_column(Text)
    geom: Mapped[object | None] = mapped_column(Geometry("POINT", srid=4326))
    home_gateway_id: Mapped[str | None] = mapped_column(Text, ForeignKey("gateways.id"))
    status: Mapped[str] = mapped_column(Text, **DB_DEFAULT)
    registered_via: Mapped[str] = mapped_column(Text)
    is_public: Mapped[bool] = mapped_column(**DB_DEFAULT)
    expected_interval_s: Mapped[int | None]
    interval_locked: Mapped[bool] = mapped_column(**DB_DEFAULT)
    observed_interval_s: Mapped[int | None]
    observed_interval_iqr_ratio: Mapped[float | None] = mapped_column(REAL)
    offline_after_s: Mapped[int | None]
    connectivity: Mapped[str] = mapped_column(Text, **DB_DEFAULT)
    last_seen_at: Mapped[datetime | None]
    last_heard_at: Mapped[datetime | None]
    last_measurement_at: Mapped[datetime | None]
    last_msg_id: Mapped[int | None] = mapped_column(SmallInteger)
    lost_packets_24h: Mapped[int | None]
    last_gateway_id: Mapped[str | None] = mapped_column(Text)
    battery_pct: Mapped[int | None] = mapped_column(SmallInteger)
    approved_at: Mapped[datetime | None]
    first_data_at: Mapped[datetime | None]
    retired_at: Mapped[datetime | None]


class NodeSensor(Base):
    """Trạng thái từng cảm biến của node: pms7003 (PM), aht10 (nhiệt/ẩm), ccs811 (CO2/TVOC)."""

    __tablename__ = "node_sensors"

    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"), primary_key=True)
    sensor: Mapped[str] = mapped_column(Text, primary_key=True)
    health: Mapped[str] = mapped_column(Text, **DB_DEFAULT)
    last_ok_at: Mapped[datetime | None]
    last_error_at: Mapped[datetime | None]
    error_streak: Mapped[int] = mapped_column(**DB_DEFAULT)


class NodeGatewayLink(Base):
    """Gateway nào đã chuyển tiếp gói của node nào (vùng phủ, phát hiện bất thường)."""

    __tablename__ = "node_gateway_links"

    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id"), primary_key=True)
    gateway_id: Mapped[str] = mapped_column(ForeignKey("gateways.id"), primary_key=True)
    first_seen_at: Mapped[datetime]
    last_seen_at: Mapped[datetime]
    packet_count: Mapped[int] = mapped_column(BigInteger)
