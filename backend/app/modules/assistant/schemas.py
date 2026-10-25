"""Dạng response của API trợ lý (09-xiaozhi-mcp §4–5).

Gọn, đã làm tròn, thời gian ISO 8601 múi giờ +07:00, có `summary_vi`; giá trị thiếu giữ null (không đổi thành 0).
Chỉ có dữ liệu môi trường: không có pin, Gateway, cấu hình hay log quản trị.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

UNITS = {"pm25": "µg/m³", "pm10": "µg/m³", "temperature": "°C", "humidity": "%"}


class StationRef(BaseModel):
    """Trạm được nhắc tới trong câu trả lời."""

    code: str  # mã trạm công khai, vd ST001
    name: str
    district: str | None


class StationItem(StationRef):
    """Một trạm trong danh sách, kèm độ mới dữ liệu."""

    online: bool  # đang gửi dữ liệu (số đo gần nhất chưa quá ngưỡng dữ liệu cũ)
    last_measured_at: datetime | None


class StationsOut(BaseModel):
    """Kết quả list_stations."""

    ok: Literal[True] = True
    stations: list[StationItem]
    default_station: str | None  # mã trạm dùng khi người dùng không nêu trạm
    summary_vi: str


class CurrentOut(BaseModel):
    """Kết quả get_current_air_quality.

    `aqi` là AQI giờ (giờ đã đóng gần nhất, nhãn `aqi_hour_end` = cửa sổ (h−1, h]); mức, nhãn, khuyến nghị theo AQI
    giờ. Chưa có AQI giờ thì `aqi` null (không thay bằng AQI tức thời). `aqi_instant` là AQI của lần đo gần nhất
    (`measured_at`), cùng lần đo với PM2.5, PM10, nhiệt độ, độ ẩm. Bỏ số đo cách ly, nghi cũ.
    """

    ok: Literal[True] = True
    station: StationRef
    aqi: int | None
    aqi_kind: Literal["hourly"]
    aqi_hour_end: datetime | None
    hourly_aqi: int | None  # giống `aqi`, giữ để tương thích bản trước
    aqi_instant: int | None
    level: str | None  # good, moderate, usg, unhealthy, very_unhealthy, hazardous (theo AQI giờ)
    level_label: str | None
    advice: str | None
    pm25: float | None
    pm10: float | None
    temperature: float | None
    humidity: float | None
    units: dict[str, str]
    measured_at: datetime  # thời điểm lần đo gần nhất (PM, nhiệt độ, độ ẩm, AQI tức thời)
    age_minutes: int  # số phút từ lúc đo tới lúc hỏi
    stale: bool  # dữ liệu cũ: trạm không gửi số đo mới quá ngưỡng
    last_updated_at: datetime | None  # lúc server nhận số đo gần nhất
    summary_vi: str


class MetricOut(BaseModel):
    """Thống kê một chỉ số trong khoảng hỏi."""

    avg: float | None
    min: float | None
    max: float | None
    n: int
    trend: str | None  # increasing, decreasing, stable, insufficient_data (chỉ AQI, PM2.5, PM10)
    trend_label: str | None


class SummaryOut(BaseModel):
    """Kết quả get_history_summary: thống kê, không trả cả chuỗi số đo."""

    ok: Literal[True] = True
    station: StationRef
    hours: int
    requested_from: datetime
    data_from: datetime  # khoảng thời gian thực tế có dữ liệu
    data_to: datetime
    n_samples: int
    metrics: dict[str, MetricOut]  # aqi, pm25, pm10, temperature, humidity
    aqi_kind: Literal["instant"]  # thống kê trên AQI tức thời của từng lần đo
    units: dict[str, str]
    summary_vi: str


class ForecastItemOut(BaseModel):
    """Một mốc dự báo; mốc độ tin cậy thấp chỉ đọc là xu hướng."""

    horizon_h: int
    target_time: datetime  # giờ đích (nhãn h = cửa sổ (h−1, h])
    aqi: int
    level: str | None
    level_label: str | None
    confidence: Literal["high", "medium", "low"]
    typical_error: float | None  # sai số tham khảo (MAE), không phải khoảng tin cậy


class ForecastBodyOut(BaseModel):
    """Dự báo đã lưu đang được dùng."""

    model_version: str
    input_hour: datetime
    issued_at: datetime  # thời điểm tính dự báo
    issue_kind: str
    items: list[ForecastItemOut]


class ForecastOut(BaseModel):
    """Kết quả get_forecast: dự báo đã tính sẵn (không chạy model khi hỏi). Không có dự báo dùng được thì `forecast`
    null kèm trạng thái và lý do (không bịa số). Cùng nguồn với /public/stations/{code}/forecast."""

    ok: Literal[True] = True
    station: StationRef
    status: Literal["ok", "stale", "insufficient_history", "no_data", "error", "unavailable"]
    horizons: list[int]
    age_hours: int | None
    forecast: ForecastBodyOut | None
    message_vi: str | None
    summary_vi: str
