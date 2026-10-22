"""Model SQLAlchemy của module telemetry (hypertable ở database_design 5.3)."""

from datetime import datetime

from sqlalchemy import BigInteger, FetchedValue, ForeignKey, Identity, Integer, SmallInteger, Text
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION, INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class IngestBatch(Base):
    """Log mỗi request từ thiết bị (telemetry, heartbeat, provision), giữ 14 ngày."""

    __tablename__ = "ingest_batches"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    gateway_id: Mapped[str | None] = mapped_column(Text)
    remote_ip: Mapped[str | None] = mapped_column(INET)
    http_status: Mapped[int] = mapped_column(SmallInteger)
    item_count: Mapped[int] = mapped_column(SmallInteger, server_default=FetchedValue())
    accepted: Mapped[int] = mapped_column(SmallInteger, server_default=FetchedValue())
    duplicates: Mapped[int] = mapped_column(SmallInteger, server_default=FetchedValue())
    superseded: Mapped[int] = mapped_column(SmallInteger, server_default=FetchedValue())
    heartbeats: Mapped[int] = mapped_column(SmallInteger, server_default=FetchedValue())
    rejected: Mapped[int] = mapped_column(SmallInteger, server_default=FetchedValue())
    has_msg_id: Mapped[bool | None]
    stale_suspected: Mapped[bool] = mapped_column(server_default=FetchedValue())
    stale_reason: Mapped[str | None] = mapped_column(Text)
    possible_age_s: Mapped[int | None]
    error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSONB)
    processing_ms: Mapped[int | None]
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default=FetchedValue())


class Measurement(Base):
    """Một số đo thô của node, giữ 90 ngày. Khóa chính (id, measured_at); measured_at được phép trùng."""

    __tablename__ = "measurements"

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    node_id: Mapped[int] = mapped_column(Integer, ForeignKey("nodes.id"))
    measured_at: Mapped[datetime] = mapped_column(primary_key=True)
    received_at: Mapped[datetime]
    max_age_s: Mapped[int | None]
    trusted_at: Mapped[datetime | None]
    superseded_at: Mapped[datetime | None]
    gateway_id: Mapped[str] = mapped_column(Text, ForeignKey("gateways.id"))
    batch_id: Mapped[int | None] = mapped_column(BigInteger)
    seq: Mapped[int] = mapped_column(SmallInteger)
    msg_id: Mapped[int | None] = mapped_column(SmallInteger)
    time_source: Mapped[str] = mapped_column(Text)
    pm25: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    pm10: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    co2: Mapped[int | None] = mapped_column(SmallInteger)
    tvoc: Mapped[int | None] = mapped_column(Integer)
    temperature: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    humidity: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    battery_pct: Mapped[int | None] = mapped_column(SmallInteger)
    aqi_instant: Mapped[int | None] = mapped_column(SmallInteger)
    qc_flags: Mapped[int] = mapped_column(Integer)
    payload_hash: Mapped[int] = mapped_column(BigInteger)
