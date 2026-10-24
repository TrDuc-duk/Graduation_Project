"""Đóng giờ, giờ đang mở, tính lại và revision (backend_design 7, 18 "Tổng hợp giờ", "Outbox")."""

from datetime import timedelta

import pytest

from app.core.db import get_sessionmaker, run_in_transaction
from app.core.scheduler import run_job
from app.modules.hourly import service
from app.modules.hourly.jobs import hourly_rollup
from app.modules.telemetry.qc import QcFlag
from tests.conftest import T0
from tests.fixtures.firmware import item, telemetry
from tests.integration.helpers import add_gateway, add_node, execute, rows, scalar
from tests.integration.test_hourly_compute import add_measurement

H14 = T0  # 14:00 giờ Việt Nam
GRACE = timedelta(seconds=180)


@pytest.fixture
def node(db):
    add_gateway(db)
    return add_node(db, 1, expected_interval_s=900, interval_locked=True)


def hourly(db):
    return rows(db, "SELECT * FROM node_hourly ORDER BY node_id, hour_end")


def revised_events(db):
    return rows(db, "SELECT payload FROM outbox_events WHERE kind = 'hourly_revised' ORDER BY id")


async def close(hour_end, now):
    return await service.close_hour(hour_end, now)


async def test_close_hour_writes_closed_row_once(db, node):
    add_measurement(db, node, H14 - timedelta(minutes=30), pm25=20.0, pm10=30.0)
    assert (await close(H14, H14 + GRACE))["closed"] == 1
    [row] = hourly(db)
    assert (row.hour_end, row.is_closed, row.revision, row.n_samples) == (H14, True, 0, 1)

    # Chạy lại (vd sau restart) không ghi lại dòng đã đóng, kể cả khi dữ liệu đã đổi
    add_measurement(db, node, H14 - timedelta(minutes=10), pm25=90.0, pm10=90.0)
    assert (await close(H14, H14 + GRACE + timedelta(hours=1)))["closed"] == 0
    assert hourly(db)[0].computed_at == row.computed_at and hourly(db)[0].pm25_avg == 20.0


async def test_close_hour_without_data_writes_nothing(db, node):
    assert (await close(H14, H14 + GRACE))["closed"] == 0
    assert hourly(db) == []


async def test_rollup_open_hours_before_and_after_grace(db, node):
    """14:01: giờ 14:00 chưa qua mốc đóng nên vẫn tính như giờ mở; 14:20 chỉ còn giờ 15:00 đang mở."""
    add_measurement(db, node, H14 - timedelta(minutes=30), pm25=20.0, pm10=30.0)
    add_measurement(db, node, H14 + timedelta(seconds=30), pm25=40.0, pm10=30.0)
    out = await service.rollup_open_hours(H14 + timedelta(minutes=1))
    assert out["written"] == 2
    assert [(r.hour_end, r.is_closed) for r in hourly(db)] == [(H14, False), (H14 + timedelta(hours=1), False)]

    await close(H14, H14 + GRACE)
    out = await service.rollup_open_hours(H14 + timedelta(minutes=20))
    assert out["open_hours"] == [(H14 + timedelta(hours=1)).isoformat()]
    assert [(r.hour_end, r.is_closed, r.revision) for r in hourly(db)] == [
        (H14, True, 0),
        (H14 + timedelta(hours=1), False, 0),
    ]


async def test_late_data_increments_revision_and_publishes_outbox(db, node):
    """Dữ liệu muộn vào giờ đã đóng → xếp hàng → revision 1 + outbox; tính lại không đổi → không có sự kiện mới."""
    add_measurement(db, node, H14 - timedelta(minutes=30), pm25=20.0, pm10=30.0)
    await close(H14, H14 + GRACE)
    now = H14 + timedelta(minutes=10)
    add_measurement(db, node, H14 - timedelta(minutes=5), received_at=now, pm25=40.0, pm10=30.0)
    async with get_sessionmaker()() as session:
        assert await service.enqueue_closed_hours(session, node, [H14 - timedelta(minutes=5)], now) == 1
        await session.commit()

    assert await service.process_recompute_queue(now) == {"processed": 1, "revised": 1}
    [row] = hourly(db)
    assert (row.revision, row.pm25_avg, row.n_samples) == (1, 30.0, 2)
    assert [e.payload for e in revised_events(db)] == [{"node_id": node, "hour_end": H14.isoformat(), "revision": 1}]
    assert scalar(db, "SELECT partition_key FROM outbox_events WHERE kind = 'hourly_revised'") == f"node:{node}"

    await run_in_transaction(lambda s: service.enqueue_recompute(s, node, H14))
    assert await service.process_recompute_queue(now) == {"processed": 1, "revised": 0}
    assert hourly(db)[0].revision == 1 and len(revised_events(db)) == 1
    assert scalar(db, "SELECT count(*) FROM hourly_recompute_queue") == 0


async def test_open_hour_is_not_queued_and_queue_waits_for_grace(db, node):
    """Thời điểm đo thuộc giờ chưa qua mốc đóng không vào hàng đợi; mục chưa tới mốc đóng chưa được xử lý."""
    async with get_sessionmaker()() as session:
        assert await service.enqueue_closed_hours(session, node, [H14 - timedelta(minutes=1)], H14) == 0
        await service.enqueue_recompute(session, node, H14)
        await session.commit()
    assert await service.process_recompute_queue(H14 + timedelta(minutes=1)) == {"processed": 0, "revised": 0}
    assert scalar(db, "SELECT count(*) FROM hourly_recompute_queue") == 1


async def test_late_data_into_hour_without_row_creates_closed_row(db, node):
    """Giờ đã qua mốc đóng mà node chưa có dòng: tính lại tạo dòng đã đóng revision 0 và báo outbox."""
    now = H14 + timedelta(hours=2)
    add_measurement(db, node, H14 - timedelta(minutes=5), received_at=now, pm25=40.0, pm10=30.0)
    await run_in_transaction(lambda s: service.enqueue_recompute(s, node, H14))
    assert (await service.process_recompute_queue(now))["revised"] == 1
    [row] = hourly(db)
    assert (row.is_closed, row.revision) == (True, 0)
    assert revised_events(db)[0].payload["revision"] == 0


async def test_hour_losing_all_samples_keeps_row_with_new_revision(db, node):
    """Mọi bản của giờ đã đóng bị thay (sang giờ khác): giữ dòng với số đếm 0 để không mất revision."""
    add_measurement(db, node, H14 - timedelta(minutes=30), pm25=20.0, pm10=30.0)
    await close(H14, H14 + GRACE)
    execute(
        db,
        "UPDATE measurements SET qc_flags = qc_flags | :f, superseded_at = received_at + interval '1 minute'",
        f=int(QcFlag.SUPERSEDED),
    )
    await run_in_transaction(lambda s: service.enqueue_recompute(s, node, H14))
    assert (await service.process_recompute_queue(H14 + timedelta(hours=1)))["revised"] == 1
    [row] = hourly(db)
    assert (row.n_samples, row.pm25_avg, row.aqi, row.coverage, row.revision) == (0, None, None, 0.0, 1)


async def test_close_removes_pending_queue_entries(db, node):
    """Đóng giờ lần đầu đã tính từ dữ liệu mới nhất nên bỏ mục hàng đợi của giờ đó."""
    add_measurement(db, node, H14 - timedelta(minutes=30), pm25=20.0, pm10=30.0)
    await run_in_transaction(lambda s: service.enqueue_recompute(s, node, H14))
    await close(H14, H14 + GRACE)
    assert scalar(db, "SELECT count(*) FROM hourly_recompute_queue") == 0
    assert revised_events(db) == []


async def test_ingest_into_closed_hour_queues_recompute(client, db, node, clock):
    """Batch đến lúc 14:04 (sau khi đóng giờ 14:00) có bản ghi lùi theo chu kỳ 15 phút về giờ 14:00 →
    ingest xếp hàng giờ 14:00; rollup tính lại → revision 1."""
    add_measurement(db, node, H14 - timedelta(minutes=50), pm25=10.0, pm10=10.0)
    await close(H14, H14 + GRACE)
    clock.advance(minutes=4)
    items = [item(msg_id=None, pm25=30.0 + i) for i in range(3)]
    r = await client.post("/api/v1/telemetry", json=telemetry(items=items))
    assert r.status_code == 200 and r.json()["accepted"] == 3
    times = [m.measured_at for m in rows(db, "SELECT measured_at FROM measurements WHERE pm25 > 20 ORDER BY seq")]
    assert times[-1] == H14 + timedelta(minutes=4)
    assert any(t <= H14 for t in times)  # có bản rơi vào giờ đã đóng
    assert [r.hour_end for r in rows(db, "SELECT hour_end FROM hourly_recompute_queue")] == [H14]

    assert await run_job("hourly_rollup", hourly_rollup) == "ok"
    h14 = next(r for r in hourly(db) if r.hour_end == H14)
    assert h14.revision == 1 and h14.n_samples > 1
    assert scalar(db, "SELECT status FROM job_runs WHERE job = 'hourly_rollup'") == "ok"


async def test_pending_gateway_data_counted_as_excluded(client, db, clock):
    """Dữ liệu qua Gateway chờ duyệt không vào trung bình giờ, chỉ đếm n_excluded (S1)."""
    add_gateway(db, status="pending")
    node_id = add_node(db, 1, expected_interval_s=900, interval_locked=True)
    clock.at = H14 - timedelta(minutes=10)
    assert (await client.post("/api/v1/telemetry", json=telemetry())).status_code == 200
    await close(H14, H14 + GRACE)
    [row] = hourly(db)
    assert (row.node_id, row.n_samples, row.n_excluded, row.pm25_avg, row.is_closed) == (node_id, 0, 1, None, True)


async def test_close_waits_for_ingest_lock_of_node(db, node):
    """Đóng giờ dùng chung khóa địa chỉ node với ingest (R10): đang có transaction giữ khóa thì phải chờ,
    nên kết quả tính luôn thấy dữ liệu ingest vừa commit."""
    import asyncio

    from app.core.locks import address_key, node_address_locks

    add_measurement(db, node, H14 - timedelta(minutes=30), pm25=20.0, pm10=30.0)
    async with get_sessionmaker()() as holder, holder.begin():
        await node_address_locks(holder, [address_key(1, 1)])
        task = asyncio.create_task(close(H14, H14 + GRACE))
        await asyncio.sleep(0.3)
        assert not task.done()
        add_measurement(db, node, H14 - timedelta(minutes=10), pm25=40.0, pm10=30.0)  # commit trước khi nhả khóa
    assert (await task)["closed"] == 1
    assert hourly(db)[0].pm25_avg == 30.0
