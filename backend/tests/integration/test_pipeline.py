"""Đường ống giờ, bước 1 (backend_design 7.1, 18 "Đường ống giờ"): chạy bù, idempotent, lỗi giữa chừng, khóa."""

from datetime import timedelta

import pytest

from app.core.db import get_sessionmaker
from app.core.locks import pipeline_lock
from app.core.scheduler import run_job
from app.modules.pipeline import service
from app.modules.pipeline.jobs import hourly_pipeline
from tests.conftest import T0
from tests.integration.helpers import add_gateway, add_node, rows, scalar
from tests.integration.test_hourly_compute import add_measurement

H14 = T0  # 14:00 giờ Việt Nam
HOUR = timedelta(hours=1)


@pytest.fixture
def node(db):
    add_gateway(db)
    return add_node(db, 1, expected_interval_s=900, interval_locked=True)


def pipeline_rows(db):
    return rows(db, "SELECT * FROM hour_pipeline ORDER BY hour_end")


def closed_hours(db):
    return [r.hour_end for r in rows(db, "SELECT hour_end FROM node_hourly WHERE is_closed ORDER BY hour_end")]


def advisory_locks_of_pipeline(db) -> int:
    return scalar(db, "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND classid = 3")


async def test_first_run_on_empty_db_starts_at_latest_closable_hour(db, node):
    """DB trống: chỉ bắt đầu từ giờ đóng được mới nhất; 14:02:59 chưa qua mốc đóng 14:03 của giờ 14:00."""
    add_measurement(db, node, H14 - timedelta(minutes=30), pm25=20.0, pm10=30.0)
    assert await service.run(H14 + timedelta(minutes=2, seconds=59)) == {"done": 1}
    assert [r.hour_end for r in pipeline_rows(db)] == [H14 - HOUR]

    assert await service.run(H14 + timedelta(minutes=3)) == {"done": 1}
    assert [(r.hour_end, r.closed_at is not None) for r in pipeline_rows(db)] == [(H14 - HOUR, True), (H14, True)]
    assert closed_hours(db) == [H14]


async def test_catch_up_after_5_hour_outage_in_order(db, node, monkeypatch):
    """Tắt 5 giờ rồi bật: đóng đủ 5 giờ theo thứ tự; chạy lại không tạo bản ghi trùng."""
    await service.run(H14 + timedelta(minutes=3))
    for i in range(1, 6):
        add_measurement(db, node, H14 + i * HOUR - timedelta(minutes=20), pm25=10.0 * i, pm10=30.0)

    calls = []
    real_close = service.hourly.close_hour

    async def recording_close(hour_end, now):
        calls.append(hour_end)
        return await real_close(hour_end, now)

    monkeypatch.setattr(service.hourly, "close_hour", recording_close)
    assert await service.run(H14 + 5 * HOUR + timedelta(minutes=5)) == {"done": 5}
    assert calls == [H14 + i * HOUR for i in range(1, 6)]
    assert closed_hours(db) == [H14 + i * HOUR for i in range(1, 6)]

    assert await service.run(H14 + 5 * HOUR + timedelta(minutes=6)) == {"done": 0}
    assert scalar(db, "SELECT count(*) FROM hour_pipeline") == 6
    assert scalar(db, "SELECT count(*) FROM node_hourly") == 5


async def test_failed_hour_blocks_later_hours_then_resumes(db, node, monkeypatch):
    """Lỗi ở giờ 17:00: giờ trước xong, giờ sau phải chờ; lần sau làm tiếp đúng từ giờ lỗi."""
    await service.run(H14 + timedelta(minutes=3))
    real_close = service.hourly.close_hour

    async def flaky_close(hour_end, now):
        if hour_end == H14 + 3 * HOUR:
            raise RuntimeError("DB tạm lỗi")
        return await real_close(hour_end, now)

    monkeypatch.setattr(service.hourly, "close_hour", flaky_close)
    out = await service.run(H14 + 5 * HOUR + timedelta(minutes=5))
    assert out == {"done": 2, "failed_hour": (H14 + 3 * HOUR).isoformat()}
    by_hour = {r.hour_end: r for r in pipeline_rows(db)}
    assert by_hour[H14 + 3 * HOUR].attempts == 1 and "DB tạm lỗi" in by_hour[H14 + 3 * HOUR].last_error
    assert by_hour[H14 + 4 * HOUR].closed_at is None and by_hour[H14 + 5 * HOUR].closed_at is None
    assert advisory_locks_of_pipeline(db) == 0

    monkeypatch.setattr(service.hourly, "close_hour", real_close)
    assert await service.run(H14 + 5 * HOUR + timedelta(minutes=6)) == {"done": 3}
    assert all(r.closed_at is not None and r.last_error is None for r in pipeline_rows(db))


async def test_concurrent_run_is_skipped_and_lock_released(db, node):
    """Khóa (3, 0): lượt thứ hai trong lúc lượt đầu đang giữ khóa thì bỏ qua; xong thì không rò khóa."""
    async with pipeline_lock() as got:
        assert got
        assert await service.run(H14 + timedelta(minutes=3)) == {"skipped": True}
    assert advisory_locks_of_pipeline(db) == 0
    assert (await service.run(H14 + timedelta(minutes=3)))["done"] == 1


async def test_runs_are_bounded_per_trigger(db, node, monkeypatch):
    """Mỗi lượt xử lý tối đa MAX_HOURS_PER_RUN giờ; các lượt sau làm tiếp."""
    await service.run(H14 + timedelta(minutes=3))
    monkeypatch.setattr(service, "MAX_HOURS_PER_RUN", 2)
    now = H14 + 5 * HOUR + timedelta(minutes=5)
    assert [(await service.run(now))["done"] for _ in range(4)] == [2, 2, 1, 0]


async def test_gap_older_than_retention_is_not_backfilled(db, node):
    """Giờ cũ hơn 90 ngày không còn dữ liệu thô: không thêm vào đường ống."""
    await service.run(H14 + timedelta(minutes=3))
    now = H14 + timedelta(days=100, minutes=3)
    await service.run(now)
    first_new = rows(db, "SELECT min(hour_end) AS h FROM hour_pipeline WHERE hour_end > :t", t=H14)[0].h
    assert first_new >= now - timedelta(days=90) - HOUR


async def test_job_and_progress(db, node, clock):
    """Job hourly_pipeline chạy qua scheduler (ghi job_runs); progress liệt kê giờ chưa xong/lỗi."""
    clock.at = H14 + timedelta(minutes=3)
    assert await run_job("hourly_pipeline", hourly_pipeline) == "ok"
    assert scalar(db, "SELECT status FROM job_runs WHERE job = 'hourly_pipeline'") == "ok"
    async with get_sessionmaker()() as session:
        p = await service.progress(session)
    assert (p["latest_hour"], p["steps"], p["pending"]) == (H14, ["closed_at"], [])
