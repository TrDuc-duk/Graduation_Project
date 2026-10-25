"""Hợp đồng bridge ↔ backend: gọi đúng hàm tool của xiaozhi-bridge vào server FastAPI thật (B7, 09-xiaozhi-mcp).

Không mock HTTP: kết quả tool phải là response thật của API trợ lý, cùng số liệu với API công khai.
"""

import asyncio
import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest

from app.modules.hourly import service as hourly
from tests.conftest import T0
from tests.integration.helpers import add_gateway
from tests.integration.test_hourly_compute import add_measurement
from tests.integration.test_public_api import HN, station

BRIDGE = Path(__file__).resolve().parents[3] / "xiaozhi-bridge" / "aqi_tools.py"


@pytest.fixture
def tools(live_server, monkeypatch):
    """Module aqi_tools của bridge, trỏ tới server thật với token trợ lý của test."""
    monkeypatch.setenv("API_BASE", f"{live_server}/api/v1/assistant")
    monkeypatch.setenv("ASSISTANT_TOKEN", "test-assistant-token")
    spec = importlib.util.spec_from_file_location("aqi_tools_contract", BRIDGE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def call(fn, args: dict) -> dict:
    """Tool của bridge dùng urllib (đồng bộ): chạy trong thread để không chặn server cùng event loop."""
    return await asyncio.to_thread(fn, args)


@pytest.mark.skipif(not BRIDGE.exists(), reason="không có mã xiaozhi-bridge")
async def test_bridge_tools_against_real_backend(db, clock, tools, live_server):
    import httpx

    add_gateway(db)
    node = station(db, 1, HN, name="Bách Khoa")
    add_measurement(db, node, T0 - timedelta(minutes=30), pm25=43.0, pm10=51.0)
    await hourly.close_hour(T0, T0 + timedelta(minutes=3))
    clock.at = T0 + timedelta(minutes=10)

    listed = await call(tools.list_stations, {})
    assert listed["ok"] is True and [s["code"] for s in listed["stations"]] == ["ST001"]

    current = await call(tools.get_current_air_quality, {"station": "bach khoa"})
    async with httpx.AsyncClient() as http:
        public = (await http.get(f"{live_server}/api/v1/public/stations/ST001")).json()
    assert current["ok"] is True and current["aqi_kind"] == "hourly"
    assert current["aqi"] == public["hourly"]["aqi"] == 119 and current["level"] == public["hourly"]["level"]
    assert current["aqi_hour_end"] == public["hourly"]["hour_end"]

    summary = await call(tools.get_history_summary, {"station": "ST001", "hours": 6})
    assert summary["ok"] is True and summary["n_samples"] == 1

    missing = await call(tools.get_current_air_quality, {"station": "ST999"})
    assert (missing["ok"], missing["code"]) == (False, "STATION_NOT_FOUND")
    bad = await call(tools.get_history_summary, {"station": "ST001", "hours": 100})
    assert (bad["ok"], bad["code"]) == (False, "INVALID_PARAMS")
