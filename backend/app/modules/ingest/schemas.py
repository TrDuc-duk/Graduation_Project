"""Dạng JSON firmware gửi lên (backend_design 6.1; datn-main/firmware/gateway/src/net/http_client.cpp)."""

from pydantic import BaseModel, Field, field_validator, model_validator

GATEWAY_ID_PATTERN = r"^[A-Za-z0-9_-]{1,15}$"  # char[16] trong firmware, khớp CHECK của bảng gateways
MAX_ITEMS = 50  # firmware gửi tối đa 10


class TelemetryItem(BaseModel):
    """Một gói LoRa Gateway chuyển tiếp. Cảm biến lỗi thì firmware gửi null (PM, nhiệt, ẩm) hoặc 0/65535 (CO2)."""

    node_id: str
    pm25: float | None = None
    pm10: float | None = None
    co2: float | None = None
    tvoc: float | None = None
    temperature: float | None = None
    humidity: float | None = None
    battery: float | None = None
    rssi: float | None = None  # module AS32 không đo được RSSI, luôn 0 → bỏ qua
    msg_id: int | None = None  # chỉ bản firmware `gateway` gửi; `gateway-30pin` không có

    @field_validator("msg_id", mode="before")
    @classmethod
    def msg_id_in_byte_range(cls, v: object) -> object:
        """msg_id là bộ đếm 1 byte; ngoài 0–255 coi như không có."""
        return v if isinstance(v, int) and 0 <= v <= 255 else None


class TelemetryIn(BaseModel):
    """Body POST /api/v1/telemetry: {gateway_id, secret, data: [...]}."""

    gateway_id: str = Field(pattern=GATEWAY_ID_PATTERN)
    secret: str | None = None
    data: list[TelemetryItem]


class HeartbeatIn(BaseModel):
    """Body POST /api/v1/telemetry/heartbeat: {gateway_id, secret}."""

    gateway_id: str = Field(pattern=GATEWAY_ID_PATTERN)
    secret: str | None = None


class ProvisionGatewayIn(BaseModel):
    """Body POST /api/v1/provision/gateway từ cổng cấu hình WiFi của Gateway."""

    name: str = Field(min_length=1, max_length=100)
    location_desc: str | None = Field(default=None, max_length=255)


class ProvisionNodeIn(BaseModel):
    """Body POST /api/v1/provision/node từ cổng cấu hình của node. lat/lng gửi cùng nhau hoặc không gửi."""

    name: str = Field(min_length=1, max_length=100)
    gateway_id: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def lat_lng_together(self) -> "ProvisionNodeIn":
        """Chỉ có một trong hai tọa độ thì không hợp lệ."""
        if (self.lat is None) != (self.lng is None):
            raise ValueError("lat và lng phải gửi cùng nhau")
        return self
