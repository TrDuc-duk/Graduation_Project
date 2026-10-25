"""Gọi OpenWeatherMap Current Weather. API key chỉ nằm ở backend (`.env`), không ghi log, không gửi xuống frontend."""

import logging

import httpx

log = logging.getLogger(__name__)
# httpx ghi cả URL (có `appid` = API key) ở mức INFO: chỉ để lại cảnh báo/lỗi để key không bao giờ vào log
logging.getLogger("httpx").setLevel(logging.WARNING)

BASE_URL = "https://api.openweathermap.org/data/2.5/weather"
TIMEOUT_S = 5.0  # gọi dịch vụ ngoài luôn có timeout 5 giây (backend_design 14.4)


class WeatherUnavailable(Exception):
    """OpenWeatherMap lỗi, quá thời gian hoặc trả dữ liệu không đọc được."""


class WeatherClient:
    """Client HTTP dùng chung một kết nối; `transport` chỉ truyền trong test (httpx.MockTransport)."""

    def __init__(self, api_key: str, transport: httpx.AsyncBaseTransport | None = None):
        self._key = api_key
        self._http = httpx.AsyncClient(timeout=TIMEOUT_S, transport=transport)

    async def fetch(self, lat: float, lng: float, lang: str) -> dict:
        """Thời tiết hiện tại tại (lat, lng): nhiệt độ °C, độ ẩm %, gió m/s, mô tả theo ngôn ngữ, icon, thời điểm."""
        params = {"lat": lat, "lon": lng, "units": "metric", "lang": lang, "appid": self._key}
        try:
            r = await self._http.get(BASE_URL, params=params)
            r.raise_for_status()
            body = r.json()
            weather = (body.get("weather") or [{}])[0]
            return {
                "temperature": body["main"]["temp"],
                "humidity": body["main"]["humidity"],
                "wind_speed": body.get("wind", {}).get("speed"),
                "description": weather.get("description"),
                "icon": weather.get("icon"),
                "observed_at": body["dt"],
            }
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            # Không ghi URL (chứa appid); chỉ ghi loại lỗi và mã HTTP nếu có
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            log.warning("OpenWeatherMap lỗi: %s (HTTP %s)", type(exc).__name__, status)
            raise WeatherUnavailable from None

    async def close(self) -> None:
        """Đóng kết nối HTTP (gọi khi tắt ứng dụng)."""
        await self._http.aclose()
