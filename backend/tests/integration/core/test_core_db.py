"""Test core cần DB: transaction thử lại, khóa job, outbox, app_settings, NOTIFY."""

import asyncio

import psycopg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core import outbox, settings_store
from app.core.db import get_sessionmaker, run_in_transaction
from app.core.events import notify
from app.core.locks import job_lock
from app.core.scheduler import run_job


async def test_run_in_transaction_commits(db):
    await run_in_transaction(lambda s: s.execute(text("INSERT INTO app_settings VALUES ('k1', '1')")))
    with db.connect() as conn:
        assert conn.scalar(text("SELECT value FROM app_settings WHERE key = 'k1'")) == 1


async def test_run_in_transaction_retries_lock_timeout_then_raises(db):
    """Khóa đang bị giữ → 55P03 (lock timeout) → thử lại 3 lần rồi ném lỗi."""
    attempts = 0

    async def take_lock(session):
        nonlocal attempts
        attempts += 1
        await session.execute(text("SELECT pg_advisory_xact_lock(99, 1)"))

    with db.connect() as holder:
        holder.execute(text("SELECT pg_advisory_lock(99, 1)"))
        with pytest.raises(DBAPIError) as err:
            await run_in_transaction(take_lock, lock_timeout="100ms")
        holder.execute(text("SELECT pg_advisory_unlock(99, 1)"))
    assert err.value.orig.sqlstate == "55P03"
    assert attempts == 4  # 1 lần đầu + 3 lần thử lại


async def test_run_in_transaction_does_not_retry_other_errors(db):
    attempts = 0

    async def duplicate_key(session):
        nonlocal attempts
        attempts += 1
        await session.execute(text("INSERT INTO app_settings VALUES ('dup', '1'), ('dup', '2')"))

    with pytest.raises(IntegrityError):
        await run_in_transaction(duplicate_key)
    assert attempts == 1


async def test_job_lock_is_exclusive_and_released(db):
    async with job_lock("interval_stats") as first, job_lock("interval_stats") as second:
        assert first and not second
    async with job_lock("interval_stats") as again:
        assert again
    with db.connect() as conn:  # không rò khóa phiên
        assert conn.scalar(text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'")) == 0


async def test_run_job_logs_ok_error_and_skipped(db):
    async def ok():
        return {"n": 1}

    async def boom():
        raise RuntimeError("x")

    assert await run_job("cleanup", ok) == "ok"
    assert await run_job("cleanup", boom) == "error"
    async with job_lock("cleanup"):
        assert await run_job("cleanup", ok) == "skipped"
    with db.connect() as conn:
        rows = conn.execute(text("SELECT status, stats FROM job_runs ORDER BY id")).all()
    assert [r.status for r in rows] == ["ok", "error", "skipped"]
    assert rows[0].stats == {"n": 1}


async def test_settings_store_db_overrides_default(db):
    assert await settings_store.get("max_msg_gap") == 20
    await run_in_transaction(lambda s: s.execute(text("INSERT INTO app_settings VALUES ('max_msg_gap', '5')")))
    assert await settings_store.get("max_msg_gap") == 20  # còn cache
    settings_store.clear_cache()
    assert await settings_store.get("max_msg_gap") == 5


# ---------- outbox ----------


async def _publish(kind, payload, key):
    await run_in_transaction(lambda s: outbox.publish(s, kind, payload, key))


def _statuses(db):
    with db.connect() as conn:
        return conn.execute(text("SELECT id, status, attempts FROM outbox_events ORDER BY id")).all()


async def test_outbox_event_without_handler_is_done(db):
    await _publish("unhandled_kind", {"a": 1}, "node:1")
    assert await outbox.dispatch_once() == {"done": 1, "retry": 0, "failed": 0}
    assert _statuses(db)[0].status == "done"


async def test_outbox_rollback_writes_nothing(db):
    async def publish_then_fail(session):
        await outbox.publish(session, "k", {}, "node:1")
        raise RuntimeError("rollback")

    with pytest.raises(RuntimeError):
        await run_in_transaction(publish_then_fail)
    assert _statuses(db) == []


async def test_outbox_failed_head_blocks_same_partition_only(db):
    calls = []

    async def flaky(session, payload):
        calls.append(payload["n"])
        if payload["n"] == 1:
            raise ValueError("lỗi tạm")

    outbox.register_handler("test_flaky", flaky)
    await _publish("test_flaky", {"n": 1}, "node:1")
    await _publish("test_flaky", {"n": 2}, "node:1")  # cùng khóa: phải chờ sự kiện 1
    await _publish("test_flaky", {"n": 3}, "node:2")  # khóa khác: chạy được

    stats = await outbox.dispatch_once()
    assert stats == {"done": 1, "retry": 1, "failed": 0}
    assert calls == [1, 3]
    rows = _statuses(db)
    assert [(r.status, r.attempts) for r in rows] == [("pending", 1), ("pending", 0), ("done", 0)]


async def test_outbox_fails_after_10_attempts_and_unblocks(db):
    async def always_fail(session, payload):
        if payload["n"] == 1:
            raise ValueError("hỏng")

    outbox.register_handler("test_fail", always_fail)
    await _publish("test_fail", {"n": 1}, "gateway:GW_001")
    await _publish("test_fail", {"n": 2}, "gateway:GW_001")
    for _ in range(10):
        with db.begin() as conn:  # bỏ thời gian chờ backoff để chạy lại ngay
            conn.execute(text("UPDATE outbox_events SET available_at = now() - interval '1 second'"))
        await outbox.dispatch_once()
    rows = _statuses(db)
    assert (rows[0].status, rows[0].attempts) == ("failed", 10)
    assert rows[1].status == "pending"  # sự kiện đầu vừa failed: lượt sau mới tới sự kiện 2
    await outbox.dispatch_once()
    assert _statuses(db)[1].status == "done"


async def test_notify_delivered_only_after_commit(db, migrated):
    """pg_notify trong transaction bị rollback thì không tới người nghe."""
    url = migrated.url.set(drivername="postgresql").render_as_string(hide_password=False)
    async with await psycopg.AsyncConnection.connect(url, autocommit=True) as listener:
        await listener.execute("LISTEN aqi_events")

        async def send_then_fail(session):
            await notify(session, "lost", {})
            raise RuntimeError

        with pytest.raises(RuntimeError):
            await run_in_transaction(send_then_fail)
        await run_in_transaction(lambda s: notify(s, "measurement", {"pm25": 1}, node_id=7))

        gen = listener.notifies()
        msg = await asyncio.wait_for(anext(gen), timeout=3)
        await gen.aclose()
    assert '"type": "measurement"' in msg.payload and '"node_id": 7' in msg.payload


async def test_session_uses_utc(db):
    async with get_sessionmaker()() as s:
        assert await s.scalar(text("SHOW timezone")) == "UTC"
