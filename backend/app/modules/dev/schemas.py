"""Dạng dữ liệu trả về của API dev chỉ đọc (dashboard demo)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# Đơn vị gửi kèm để frontend không hardcode (frontend_design 7)
UNITS = {
    "pm25": "µg/m³",
    "pm10": "µg/m³",
    "co2": "ppm",
    "tvoc": "ppb",
    "temperature": "°C",
    "humidity": "%",
    "battery": "%",
}


class GatewayOut(BaseModel):
    """Gateway đã chuyển tiếp số đo của node."""

    id: str
    name: str
    status: str
    online: bool  # có liên lạc trong gateway_offline_after_s
    last_seen_at: datetime | None
    last_telemetry_at: datetime | None


class Freshness(BaseModel):
    """Độ mới của số đo gần nhất, tính theo thời điểm server NHẬN dữ liệu."""

    last_received_at: datetime | None
    age_s: int | None
    stale_after_s: int
    is_stale: bool  # quá stale_after_s chưa nhận số đo mới (hoặc chưa có số đo nào)


class NodeOut(BaseModel):
    """Node (= trạm) kèm Gateway gần nhất và độ mới dữ liệu."""

    id: int
    station_code: str
    device_code: str
    name: str
    status: str  # pending: chưa được Admin duyệt, chưa công khai
    connectivity: str
    battery_pct: int | None
    effective_interval_s: int | None
    last_seen_at: datetime | None
    last_measurement_at: datetime | None
    gateway: GatewayOut | None
    freshness: Freshness


class Reading(BaseModel):
    """Một số đo thô; null nghĩa là cảm biến lỗi/thiếu, không phải 0."""

    measured_at: datetime
    received_at: datetime
    gateway_id: str
    time_source: str
    pm25: float | None
    pm10: float | None
    co2: int | None
    tvoc: int | None
    temperature: float | None
    humidity: float | None
    battery_pct: int | None
    aqi_instant: int | None  # backend tính; frontend không tự tính AQI
    qc_flags: int
    quarantined: bool  # qua Gateway chưa duyệt (cờ UNTRUSTED_GATEWAY)
    time_unreliable: bool  # batch nghi chứa dữ liệu cũ (cờ TIME_UNRELIABLE)


class NodeReadings(BaseModel):
    """Lịch sử số đo của một node trong khoảng `hours` giờ gần nhất."""

    node: NodeOut
    hours: Literal[1, 6, 24]
    since: datetime
    server_time: datetime
    units: dict[str, str]
    latest: Reading | None  # số đo mới nhất, kể cả khi nằm ngoài khoảng
    readings: list[Reading]
    truncated: bool  # quá giới hạn số điểm, chỉ trả phần mới nhất
