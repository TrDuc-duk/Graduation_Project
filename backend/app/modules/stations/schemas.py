"""Dạng response của API công khai `/public/*` (backend_design 11.3).

Thời gian ISO 8601 `+07:00`; số đo làm tròn 1 chữ số, AQI số nguyên; thiếu giữ null. Không có pin, Gateway, IP,
payload gốc. `id` là mã trạm công khai (`station_code`).
"""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, PlainSerializer

from app.core.timeutil import iso_local

LocalTime = Annotated[datetime, PlainSerializer(iso_local, return_type=str)]

UNITS = {
    "pm25": "µg/m³",
    "pm10": "µg/m³",
    "temperature": "°C",
    "humidity": "%",
    "co2": "ppm",
    "tvoc": "ppb",
}


class LatestOut(BaseModel):
    """Số đo tin cậy mới nhất (bỏ bản cách ly, nghi cũ, bị thay). `aqi_instant` là AQI của một mẫu."""

    measured_at: LocalTime
    time_estimated: bool  # thời điểm đo do server ước lượng (firmware không gửi thời điểm)
    age_minutes: int
    aqi_instant: int | None
    pm25: float | None
    pm10: float | None
    temperature: float | None
    humidity: float | None
    co2: int | None
    tvoc: int | None


class HourlyOut(BaseModel):
    """AQI giờ hiện hành: giờ đã đóng gần nhất (nhãn h = cửa sổ (h−1, h]). Số chính, quyết định màu và cảnh báo."""

    hour_end: LocalTime
    aqi: int | None
    level: str | None
    dominant: Literal["pm25", "pm10"] | None
    n_samples: int
    coverage: float | None


class StationOut(BaseModel):
    """Một trạm công khai kèm tóm tắt mới nhất."""

    id: str
    name: str
    district: str | None
    latitude: float
    longitude: float
    environment: str
    is_simulated: bool
    online: bool
    latest: LatestOut | None
    hourly: HourlyOut | None


class FreshnessOut(BaseModel):
    """Độ mới dữ liệu theo thời điểm server nhận số đo tin cậy gần nhất."""

    last_received_at: LocalTime | None
    age_s: int | None
    stale_after_s: int
    is_stale: bool


class StationDetailOut(StationOut):
    """Chi tiết trạm: như danh sách, thêm độ mới dữ liệu và đơn vị."""

    freshness: FreshnessOut
    units: dict[str, str] = UNITS


class StationsOut(BaseModel):
    items: list[StationOut]


class NearestItem(StationOut):
    distance_m: float


class NearestOut(BaseModel):
    items: list[NearestItem]


class MostPolluted(BaseModel):
    id: str
    name: str
    aqi: int
    level: str


class OverviewOut(BaseModel):
    """Tổng quan: số trạm, AQI giờ trung bình, trạm ô nhiễm nhất, cập nhật gần nhất, trạm mặc định (cho F1)."""

    n_stations: int
    n_online: int
    aqi_avg: int | None
    most_polluted: MostPolluted | None
    last_updated_at: LocalTime | None
    default_station_id: str | None


class AqiAlert(BaseModel):
    tone: Literal["ok", "info", "warning", "critical"]
    title: str
    message: str


class AqiLevelOut(BaseModel):
    level: str
    min: int
    max: int
    color: str
    soft: str
    text_color: str
    label: str
    advice: str
    alert: AqiAlert


class AqiScaleOut(BaseModel):
    items: list[AqiLevelOut]
