"""Phần thuần Python của SSE (backend_design 11.6, R12): hàng đợi hữu hạn, gộp theo trạm, lọc trường công khai."""

import asyncio

from app.modules.realtime import limits
from app.modules.realtime.hub_client import ClientQueue
from app.modules.realtime.router import to_public


def ev(kind: str, station: str = "ST001", **data) -> dict:
    return {"type": kind, "station_id": station, **data}


async def test_merges_same_type_and_station_keeps_latest():
    """measurement/hourly/station_status cùng trạm chỉ giữ bản mới nhất; khác loại không đè nhau."""
    q = ClientQueue(10)
    q.offer(ev("measurement", pm25=1))
    q.offer(ev("hourly", aqi=50))
    q.offer(ev("measurement", pm25=2))
    q.offer(ev("measurement", "ST002", pm25=9))
    assert len(q) == 3
    got = [await q.get() for _ in range(3)]
    assert got == [ev("hourly", aqi=50), ev("measurement", pm25=2), ev("measurement", "ST002", pm25=9)]


async def test_other_events_are_not_merged():
    q = ClientQueue(10)
    q.offer(ev("forecast", status="ok"))
    q.offer(ev("forecast", status="ok"))
    assert len(q) == 2


async def test_full_queue_becomes_single_resync():
    """Client chậm làm đầy hàng đợi: xóa hết, chỉ còn resync; sự kiện sau đó xếp sau resync."""
    q = ClientQueue(3)
    for i in range(3):
        q.offer(ev("measurement", f"ST00{i}"))
    q.offer(ev("measurement", "ST009"))
    assert len(q) == 1 and await q.get() == {"type": "resync"}
    q.offer(ev("hourly"))
    assert await q.get() == ev("hourly")


async def test_get_waits_for_offer():
    q = ClientQueue(5)
    waiter = asyncio.create_task(q.get())
    await asyncio.sleep(0.01)
    assert not waiter.done()
    q.offer(ev("hourly"))
    assert await asyncio.wait_for(waiter, 1) == ev("hourly")


def test_to_public_allowlist_and_time_format():
    """Chỉ trường cho phép; mã trạm công khai; thời điểm ISO +07:00; loại lạ hoặc thiếu mã trạm thì bỏ."""
    internal = {"type": "measurement", "node_id": 7, "station_code": "ST001",
                "data": {"measured_at": "2026-10-15 07:00:00+00:00", "pm25": 70.0, "pm10": 80.5, "aqi": 158,
                         "battery": 90, "gateway_id": "GW_001"}}  # fmt: skip
    assert to_public(internal) == {"type": "measurement", "station_id": "ST001",
                                   "measured_at": "2026-10-15T14:00:00+07:00", "pm25": 70.0, "pm10": 80.5,
                                   "aqi_instant": 158}  # fmt: skip
    assert to_public({"type": "device_discovered", "station_code": "ST001", "data": {}}) is None
    assert to_public({"type": "measurement", "node_id": 7, "data": {}}) is None
    assert to_public({"type": "resync"}) == {"type": "resync"}


async def test_connection_limits(db):
    """Theo IP (50) và toàn tiến trình (1000) từ app_settings; trả chỗ khi đóng."""
    assert all([await limits.try_acquire("1.1.1.1") for _ in range(50)])
    assert not await limits.try_acquire("1.1.1.1")
    assert await limits.try_acquire("2.2.2.2")
    for _ in range(50):
        limits.release("1.1.1.1")
    limits.release("2.2.2.2")
    assert limits.current() == {"total": 0, "by_ip": {}}
