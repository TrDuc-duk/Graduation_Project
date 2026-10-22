"""Chuẩn hóa từng bản ghi firmware gửi (backend_design 6.4). Thuần Python, không đụng DB."""

import math
from dataclasses import dataclass, field
from datetime import datetime

from src.aqi import compute_aqi  # cùng công thức AQI với phần ML (ml/ml_xgb/src/aqi.py)

from app.modules.devices.addressing import parse_device_code
from app.modules.ingest.dedup import payload_hash
from app.modules.ingest.schemas import TelemetryItem
from app.modules.telemetry.qc import QcFlag

PM_RANGE = (0, 1000)
# ams CCS811 datasheet v1-06 (2019-02-07): dải đầu ra, không phải ngưỡng cảnh báo.
CO2_RANGE = (400, 29206)
CO2_ERROR = 65535
TVOC_RANGE = (0, 32768)
TEMP_RANGE = (-40, 85)
HUMIDITY_RANGE = (0, 100)
HIGH_HUMIDITY = 95
BATTERY_RANGE = (0, 100)


@dataclass
class Reading:
    """Một bản ghi sau chuẩn hóa. Thời điểm đo được điền sau (timing.py)."""

    seq: int  # vị trí trong batch
    node_code: str  # chuỗi firmware gửi, ví dụ NODE_007
    addr: int | None  # địa chỉ LoRa 1–255; None nếu node_id sai mẫu
    is_heartbeat: bool  # heartbeat node: không lưu thành số đo
    pm25: float | None
    pm10: float | None
    co2: int | None
    tvoc: int | None
    temperature: float | None
    humidity: float | None
    battery_pct: int | None
    msg_id: int | None
    flags: int
    aqi_instant: int | None
    payload_hash: int
    sensor_health: dict[str, str] = field(default_factory=dict)  # cảm biến → ok/warming_up/error
    measured_at: datetime | None = None
    time_source: str | None = None


def in_range(v: float | None, bounds: tuple[float, float]) -> bool:
    """v nằm trong [min, max] (None thì không)."""
    return v is not None and bounds[0] <= v <= bounds[1]


def is_node_heartbeat(item: TelemetryItem) -> bool:
    """Heartbeat node: cả 6 giá trị đo đều đúng bằng 0 (không phải null)."""
    values = (item.pm25, item.pm10, item.temperature, item.humidity, item.co2, item.tvoc)
    return all(v == 0 for v in values)


def normalize(seq: int, item: TelemetryItem) -> Reading:
    """Đổi một gói firmware thành Reading: loại giá trị lỗi thành null, gắn cờ qc, tính AQI tức thời."""
    flags = QcFlag(0)
    heartbeat = is_node_heartbeat(item)

    pm25, pm10 = item.pm25, item.pm10
    if pm25 is not None and not in_range(pm25, PM_RANGE):
        pm25, flags = None, flags | QcFlag.PM_OUT_OF_RANGE
    if pm10 is not None and not in_range(pm10, PM_RANGE):
        pm10, flags = None, flags | QcFlag.PM_OUT_OF_RANGE
    if pm25 is not None and pm10 is not None and pm10 < pm25:
        flags |= QcFlag.PM10_LT_PM25

    co2, tvoc = item.co2, item.tvoc
    if co2 is not None and not heartbeat and not in_range(co2, CO2_RANGE):
        flags |= QcFlag.GAS_NOT_READY if co2 == 0 else QcFlag.GAS_INVALID
        co2, tvoc = None, None  # CO2 lỗi kéo theo TVOC (cùng cảm biến CCS811)
    if tvoc is not None and not heartbeat and not in_range(tvoc, TVOC_RANGE):
        tvoc, flags = None, flags | QcFlag.GAS_INVALID

    temperature, humidity = item.temperature, item.humidity
    if temperature is not None and not in_range(temperature, TEMP_RANGE):
        temperature, flags = None, flags | QcFlag.TH_OUT_OF_RANGE
    if humidity is not None and not in_range(humidity, HUMIDITY_RANGE):
        humidity, flags = None, flags | QcFlag.TH_OUT_OF_RANGE
    if humidity is not None and humidity > HIGH_HUMIDITY:
        flags |= QcFlag.HIGH_HUMIDITY

    battery = round(item.battery) if in_range(item.battery, BATTERY_RANGE) else None

    return Reading(
        seq=seq,
        node_code=item.node_id,
        addr=parse_device_code(item.node_id),
        is_heartbeat=heartbeat,
        pm25=pm25,
        pm10=pm10,
        co2=None if co2 is None else round(co2),
        tvoc=None if tvoc is None else round(tvoc),
        temperature=temperature,
        humidity=humidity,
        battery_pct=battery,
        msg_id=item.msg_id,
        flags=int(flags),
        aqi_instant=instant_aqi(pm25, pm10),
        payload_hash=payload_hash(item),
        sensor_health={} if heartbeat else sensor_health(item, pm25, pm10, temperature, humidity),
    )


def instant_aqi(pm25: float | None, pm10: float | None) -> int | None:
    """AQI tức thời từ PM2.5 và PM10; thiếu một trong hai thì không tính."""
    if pm25 is None or pm10 is None:
        return None
    value = compute_aqi(pm25, pm10)
    return None if math.isnan(value) else int(value)


def sensor_health(
    item: TelemetryItem, pm25: float | None, pm10: float | None, temperature: float | None, humidity: float | None
) -> dict[str, str]:
    """Trạng thái cảm biến suy ra từ một số đo (backend_design 6.4). Không đủ căn cứ thì không ghi cảm biến đó."""
    health: dict[str, str] = {}
    pairs = {"pms7003": (pm25, pm10), "aht10": (temperature, humidity)}
    for sensor, (a, b) in pairs.items():
        if a is not None and b is not None:
            health[sensor] = "ok"
        elif a is None and b is None:
            health[sensor] = "error"
    if item.co2 is not None:
        if in_range(item.co2, CO2_RANGE):
            health["ccs811"] = "ok"
        elif item.co2 == 0:
            health["ccs811"] = "warming_up"
        else:
            health["ccs811"] = "error"
    return health
