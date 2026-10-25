"""Thời tiết theo tọa độ trạm, cache trong tiến trình theo (tọa độ, ngôn ngữ) trong WEATHER_CACHE_TTL_S.

Khóa cache gồm tọa độ nên trạm đổi vị trí thì tự lấy dữ liệu mới. Không lưu DB.
"""

import time
from datetime import UTC, datetime

import httpx

from app.core.config import get_settings
from app.modules.weather.client import WeatherClient, WeatherUnavailable

__all__ = ["WeatherDisabled", "WeatherUnavailable", "current", "close", "use_transport"]


class WeatherDisabled(Exception):
    """Chưa cấu hình WEATHER_API_KEY: tính năng thời tiết tắt."""


_client: WeatherClient | None = None
_transport: httpx.AsyncBaseTransport | None = None  # chỉ đặt trong test
_cache: dict[tuple[float, float, str], tuple[float, dict]] = {}
_monotonic = time.monotonic


async def current(lat: float, lng: float, lang: str) -> dict:
    """Thời tiết hiện tại tại tọa độ trạm. Không có key → WeatherDisabled; lỗi/timeout → WeatherUnavailable."""
    settings = get_settings()
    if not settings.weather_api_key:
        raise WeatherDisabled
    key = (round(lat, 5), round(lng, 5), lang)
    hit = _cache.get(key)
    if hit and hit[0] > _monotonic():
        return hit[1]
    raw = await _get_client(settings.weather_api_key).fetch(lat, lng, lang)
    data = {
        "temperature": _r(raw["temperature"]),
        "humidity": raw["humidity"],
        "wind_speed": _r(raw["wind_speed"]),
        "description": raw["description"],
        "icon": raw["icon"],
        "observed_at": datetime.fromtimestamp(raw["observed_at"], UTC),
        "source": "openweathermap",
    }
    _cache[key] = (_monotonic() + settings.weather_cache_ttl_s, data)
    return data


async def close() -> None:
    """Đóng client HTTP khi tắt ứng dụng; xóa cache."""
    global _client
    if _client is not None:
        await _client.close()
    _client = None
    _cache.clear()


async def use_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Thay transport HTTP (test dùng httpx.MockTransport thay OpenWeatherMap thật)."""
    global _transport
    await close()
    _transport = transport


def _get_client(api_key: str) -> WeatherClient:
    """Client dùng chung cho cả tiến trình (tạo khi cần lần đầu)."""
    global _client
    if _client is None:
        _client = WeatherClient(api_key, _transport)
    return _client


def _r(value: float | None) -> float | None:
    return None if value is None else round(value, 1)
