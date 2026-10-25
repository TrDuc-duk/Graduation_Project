"""SSE công khai qua server Uvicorn thật (backend_design 11.6, 18 "SSE", "Outbox: rollback → không có NOTIFY")."""

import asyncio
import contextlib
import json
from datetime import timedelta

import httpx
import pytest

from app.core import events
from app.core.db import get_sessionmaker, run_in_transaction
from app.modules.hourly import service as hourly
from app.modules.realtime import limits
from tests.conftest import T0
from tests.integration.helpers import add_gateway
from tests.integration.test_hourly_compute import add_measurement
from tests.integration.test_public_api import HN, station

TIMEOUT = 5.0


@pytest.fixture
def base_url(live_server):
    """URL kênh SSE công khai trên server thật."""
    return f"{live_server}/api/v1/stream/public"


@pytest.fixture
def stations(db):
    """ST001 công khai có tọa độ; ST002 chưa có tọa độ (không công khai)."""
    add_gateway(db)
    return station(db, 1, HN), station(db, 2, None)


class Stream:
    """Đọc sự kiện SSE từ một response đang mở."""

    def __init__(self, response: httpx.Response):
        self._lines = response.aiter_lines()

    async def next(self, timeout: float = TIMEOUT) -> tuple[str, dict]:
        """Sự kiện kế tiếp (bỏ ping): (tên, dữ liệu JSON)."""
        name = None
        async with asyncio.timeout(timeout):
            async for line in self._lines:
                if line.startswith("event:"):
                    name = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and name:
                    return name, json.loads(line.split(":", 1)[1])
        raise AssertionError("stream đóng")


@contextlib.asynccontextmanager
async def open_stream(url: str, **params):
    """Mở stream, chờ sự kiện `ready` (đã đăng ký nhận sự kiện) rồi trả Stream."""
    async with (
        httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT, read=None)) as http,
        http.stream("GET", url, params=params) as r,
    ):
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        s = Stream(r)
        assert (await s.next())[0] == "ready"
        yield s


async def notify(kind: str, code: str, node_id: int, **data) -> None:
    """Phát một sự kiện trong transaction đã commit (giống ingest/hourly)."""
    await run_in_transaction(lambda s: events.notify(s, kind, data, node_id=node_id, station_code=code))


async def test_event_after_commit_reaches_client(base_url, stations):
    async with open_stream(base_url) as s:
        await notify("measurement", "ST001", stations[0], measured_at="2026-10-15 07:00:00+00:00", pm25=70.0,
                     pm10=80.5, aqi=158, battery=90)  # fmt: skip
        name, data = await s.next()
    assert name == "measurement"
    assert data == {"type": "measurement", "station_id": "ST001", "measured_at": "2026-10-15T14:00:00+07:00",
                    "pm25": 70.0, "pm10": 80.5, "aqi_instant": 158}  # fmt: skip


async def test_rollback_sends_nothing(base_url, stations):
    """NOTIFY trong transaction bị rollback không tới client; sự kiện đầu tiên nhận được là sự kiện đã commit."""
    async with open_stream(base_url) as s:
        async with get_sessionmaker()() as session:
            await session.begin()
            await events.notify(session, "measurement", {"pm25": 999.0}, node_id=stations[0], station_code="ST001")
            await session.rollback()
        await notify("measurement", "ST001", stations[0], pm25=1.0)
        assert (await s.next())[1]["pm25"] == 1.0


async def test_filters_non_public_station_and_station_param(base_url, stations):
    async with open_stream(base_url, station_id="st001") as s:
        await notify("measurement", "ST002", stations[1], pm25=5.0)  # trạm không công khai
        await notify("hourly", "ST009", 999, aqi=10)  # trạm khác
        await notify("device_discovered", "ST001", stations[0])  # loại không công khai
        await notify("hourly", "ST001", stations[0], hour_end="2026-10-15T07:00:00+00:00", aqi=51, level="moderate")
        name, data = await s.next()
    assert (name, data["station_id"], data["aqi"]) == ("hourly", "ST001", 51)


async def test_closing_hour_publishes_hourly(base_url, db, stations):
    """Đóng giờ phát `hourly {aqi, level}` để web đổi màu ngay mà không gọi REST (U4)."""
    add_measurement(db, stations[0], T0 - timedelta(minutes=30), pm25=12.0, pm10=20.0)
    add_measurement(db, stations[0], T0 - timedelta(minutes=20), pm25=12.2, pm10=20.0)
    async with open_stream(base_url) as s:
        await hourly.close_hour(T0, T0 + timedelta(minutes=3))
        name, data = await s.next()
    assert name == "hourly"
    assert data == {"type": "hourly", "station_id": "ST001", "hour_end": "2026-10-15T14:00:00+07:00", "aqi": 51,
                    "level": "moderate"}  # fmt: skip


async def test_per_ip_limit_and_release(base_url, stations):
    """60 kết nối từ một IP: 50 được nhận, 10 nhận 429 SSE_LIMIT; đóng hết thì trả đủ chỗ."""
    async with contextlib.AsyncExitStack() as stack:
        for _ in range(50):
            await stack.enter_async_context(open_stream(base_url))
        async with httpx.AsyncClient(timeout=TIMEOUT) as http:
            rejected = [await http.get(base_url) for _ in range(10)]
        assert {r.status_code for r in rejected} == {429}
        assert rejected[0].json()["error"]["code"] == "SSE_LIMIT"
        assert limits.current()["total"] == 50
    for _ in range(50):
        if limits.current()["total"] == 0:
            break
        await asyncio.sleep(0.05)
    assert limits.current()["total"] == 0
