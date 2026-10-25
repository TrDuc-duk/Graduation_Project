"""Thời tiết qua backend (backend_design 11.11, 18 "Thời tiết"): server OpenWeatherMap giả bằng httpx.MockTransport."""

import logging

import httpx
import pytest

from app.core.config import get_settings
from app.modules.weather import service as weather
from tests.integration.helpers import add_gateway, execute
from tests.integration.test_public_api import HN, station

URL = "/api/v1/public/stations/ST001/weather"
FAKE_KEY = "test-weather-key-123"
OWM_BODY = {
    "weather": [{"description": "mây rải rác", "icon": "03d"}],
    "main": {"temp": 29.04, "humidity": 78},
    "wind": {"speed": 2.14},
    "dt": 1_791_098_400,  # 2026-10-04T07:20:00Z
}


class FakeOwm:
    """OpenWeatherMap giả: ghi lại request, trả theo `mode` (ok | error | timeout | garbage)."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.mode = "ok"

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.mode == "timeout":
            raise httpx.ReadTimeout("chậm", request=request)
        if self.mode == "error":
            return httpx.Response(500, json={"message": "lỗi"})
        if self.mode == "garbage":
            return httpx.Response(200, text="không phải JSON")
        return httpx.Response(200, json=OWM_BODY)


@pytest.fixture
async def owm(db, monkeypatch):
    """Bật thời tiết với key giả và server giả; ST001 ở Bách Khoa."""
    add_gateway(db)
    station(db, 1, HN)
    monkeypatch.setenv("WEATHER_API_KEY", FAKE_KEY)
    get_settings.cache_clear()
    fake = FakeOwm()
    await weather.use_transport(httpx.MockTransport(fake))
    yield fake
    await weather.use_transport(None)
    get_settings.cache_clear()


async def test_disabled_without_key(client, db, monkeypatch):
    add_gateway(db)
    station(db, 1, HN)
    monkeypatch.setenv("WEATHER_API_KEY", "")
    get_settings.cache_clear()
    try:
        r = await client.get(URL)
    finally:
        get_settings.cache_clear()
    assert r.status_code == 503 and r.json()["error"]["code"] == "WEATHER_DISABLED"


async def test_current_weather_fields_and_request(client, owm, caplog):
    caplog.set_level(logging.DEBUG)
    r = await client.get(URL, headers={"Accept-Language": "en"})
    assert r.status_code == 200
    assert r.json() == {
        "temperature": 29.0,
        "humidity": 78,
        "wind_speed": 2.1,
        "description": "mây rải rác",
        "icon": "03d",
        "observed_at": "2026-10-04T14:20:00+07:00",
        "source": "openweathermap",
    }
    [req] = owm.requests
    q = dict(req.url.params)
    assert (q["lat"], q["lon"], q["units"], q["lang"], q["appid"]) == (str(HN[0]), str(HN[1]), "metric", "en", FAKE_KEY)
    assert FAKE_KEY not in r.text and FAKE_KEY not in caplog.text


async def test_cache_by_coordinates_and_language(client, db, owm, monkeypatch):
    """Cùng (tọa độ, ngôn ngữ) trong TTL chỉ gọi một lần; đổi ngôn ngữ, hết hạn, đổi vị trí thì gọi lại."""
    clock = [1000.0]
    monkeypatch.setattr(weather, "_monotonic", lambda: clock[0])
    await client.get(URL)
    await client.get(URL)
    assert len(owm.requests) == 1
    await client.get(URL, params={"lang": "en"})
    assert len(owm.requests) == 2
    clock[0] += get_settings().weather_cache_ttl_s + 1
    await client.get(URL)
    assert len(owm.requests) == 3
    execute(db, "UPDATE nodes SET geom = ST_SetSRID(ST_MakePoint(105.9, 21.1), 4326)")
    await client.get(URL)
    assert len(owm.requests) == 4


@pytest.mark.parametrize("mode", ["error", "timeout", "garbage"])
async def test_upstream_failure_is_503(client, owm, mode):
    owm.mode = mode
    r = await client.get(URL)
    assert r.status_code == 503 and r.json()["error"]["code"] == "WEATHER_UNAVAILABLE"
    # Thẻ thời tiết lỗi không làm hỏng chi tiết trạm
    assert (await client.get("/api/v1/public/stations/ST001")).status_code == 200


async def test_unknown_station(client, owm):
    assert (await client.get("/api/v1/public/stations/ST404/weather")).status_code == 404
    assert owm.requests == []
