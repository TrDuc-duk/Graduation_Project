"""Sự kiện realtime qua NOTIFY (database_design 8.5). Gửi trong transaction nên chỉ đến sau commit."""

import json
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger(__name__)

CHANNEL = "aqi_events"
MAX_PAYLOAD_BYTES = 8000  # giới hạn của pg_notify


async def notify(session: AsyncSession, type_: str, data: dict, **ids: object) -> None:
    """Phát sự kiện {type, ...ids, data} cho SSE. Payload quá lớn thì bỏ data (client tự đồng bộ lại)."""
    payload = json.dumps({"type": type_, **ids, "data": data}, default=str)
    if len(payload.encode()) > MAX_PAYLOAD_BYTES:
        log.warning("Bỏ data của sự kiện %s vì payload quá %d byte", type_, MAX_PAYLOAD_BYTES)
        payload = json.dumps({"type": type_, **ids, "data": None}, default=str)
    await session.execute(text("SELECT pg_notify(:ch, :p)"), {"ch": CHANNEL, "p": payload})
