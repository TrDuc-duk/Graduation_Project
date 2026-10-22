"""Outbox: việc phát sinh từ dữ liệu, ghi cùng transaction rồi xử lý nền (backend_design 6.9).

- publish(): module ghi sự kiện trong transaction nghiệp vụ.
- register_handler(): module khác đăng ký hàm xử lý theo `kind`.
- dispatch_once(): job nền lấy sự kiện đầu hàng của mỗi partition_key và xử lý từng cái.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import run_in_transaction

log = logging.getLogger(__name__)

Handler = Callable[[AsyncSession, dict], Awaitable[None]]

MAX_ATTEMPTS = 10
MAX_BACKOFF = timedelta(minutes=10)
BATCH_SIZE = 100

_handlers: dict[str, Handler] = {}


async def publish(session: AsyncSession, kind: str, payload: dict, partition_key: str | None) -> None:
    """Ghi một sự kiện vào outbox trong transaction hiện tại và đánh thức dispatcher sau commit."""
    await session.execute(
        text("INSERT INTO outbox_events (kind, partition_key, payload) VALUES (:k, :pk, CAST(:p AS jsonb))"),
        {"k": kind, "pk": partition_key, "p": json.dumps(payload, default=str)},
    )
    await session.execute(text("SELECT pg_notify('outbox', '')"))


def register_handler(kind: str, handler: Handler) -> None:
    """Đăng ký hàm xử lý cho một loại sự kiện. Handler phải idempotent (chạy lại không sai)."""
    _handlers[kind] = handler


def backoff(attempts: int) -> timedelta:
    """Thời gian chờ trước lần thử sau: 2^attempts giây, tối đa 10 phút."""
    return min(timedelta(seconds=2**attempts), MAX_BACKOFF)


# Sự kiện "đầu hàng": không còn sự kiện pending nào cùng partition_key có id nhỏ hơn (R17)
_HEAD_OF_LINE_SQL = text("""
    SELECT e.id FROM outbox_events e
    WHERE e.status = 'pending' AND e.available_at <= now()
      AND NOT EXISTS (
        SELECT 1 FROM outbox_events p
        WHERE p.status = 'pending' AND p.partition_key = e.partition_key AND p.id < e.id)
    ORDER BY e.id LIMIT :n
""")


async def dispatch_once() -> dict:
    """Xử lý một lượt tối đa 100 sự kiện; mỗi sự kiện một transaction riêng. Trả thống kê lượt chạy."""

    async def head_ids(session: AsyncSession) -> list[int]:
        return list((await session.scalars(_HEAD_OF_LINE_SQL, {"n": BATCH_SIZE})).all())

    stats = {"done": 0, "retry": 0, "failed": 0}
    for event_id in await run_in_transaction(head_ids):
        result = await _process(event_id)
        if result:
            stats[result] += 1
    return stats


async def _process(event_id: int) -> str | None:
    """Khóa một sự kiện, chạy handler và đánh dấu done trong cùng transaction; lỗi thì hẹn thử lại."""

    async def handle(session: AsyncSession) -> str | None:
        row = (
            await session.execute(
                text(
                    "SELECT kind, payload FROM outbox_events "
                    "WHERE id = :id AND status = 'pending' FOR UPDATE SKIP LOCKED"
                ),
                {"id": event_id},
            )
        ).first()
        if row is None:  # tiến trình khác đang xử lý hoặc đã xong
            return None
        handler = _handlers.get(row.kind)
        if handler:
            await handler(session, row.payload)
        await session.execute(
            text("UPDATE outbox_events SET status = 'done', processed_at = now() WHERE id = :id"),
            {"id": event_id},
        )
        return "done"

    try:
        return await run_in_transaction(handle)
    except Exception as exc:  # noqa: BLE001 — mọi lỗi của handler đều phải ghi lại để thử lại
        log.exception("Outbox event %s lỗi", event_id)
        error = repr(exc)
        return await run_in_transaction(lambda s: _mark_failed_attempt(s, event_id, error))


async def _mark_failed_attempt(session: AsyncSession, event_id: int, error: str) -> str:
    """Tăng số lần thử; quá 10 lần thì chuyển failed để mở khóa cho sự kiện sau cùng partition_key."""
    attempts = await session.scalar(
        text("UPDATE outbox_events SET attempts = attempts + 1, last_error = :e WHERE id = :id RETURNING attempts"),
        {"id": event_id, "e": error[:2000]},
    )
    if attempts >= MAX_ATTEMPTS:
        await session.execute(text("UPDATE outbox_events SET status = 'failed' WHERE id = :id"), {"id": event_id})
        return "failed"
    await session.execute(
        text("UPDATE outbox_events SET available_at = now() + :d WHERE id = :id"),
        {"id": event_id, "d": backoff(attempts)},
    )
    return "retry"
