"""Sự kiện realtime qua NOTIFY (database_design 8.5). Gửi trong transaction nên chỉ đến sau commit."""

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable

import psycopg
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings

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


class EventHub:
    """Một kết nối `LISTEN aqi_events` riêng cho mỗi tiến trình API (không lấy từ pool), chia sự kiện cho người nghe.

    Mất kết nối thì nối lại với thời gian chờ tăng dần; nối lại xong phát `{"type": "resync"}` vì có thể đã lỡ sự
    kiện (backend_design 11.6). Người nghe là hàm đồng bộ, không được chặn (chỉ đẩy vào hàng đợi của client).
    """

    def __init__(self) -> None:
        self._listeners: set[Callable[[dict], None]] = set()
        self._task: asyncio.Task | None = None
        self.connected = asyncio.Event()

    def subscribe(self, listener: Callable[[dict], None]) -> Callable[[], None]:
        """Đăng ký người nghe; trả hàm hủy đăng ký."""
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    def publish_local(self, event: dict) -> None:
        """Chia một sự kiện cho mọi người nghe trong tiến trình (lỗi của một người nghe không ảnh hưởng người khác)."""
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:  # noqa: BLE001
                log.exception("Người nghe sự kiện realtime lỗi")

    async def start(self) -> None:
        """Chạy vòng LISTEN nền (gọi trong lifespan của tiến trình có HTTP)."""
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="event-hub")

    async def stop(self) -> None:
        """Dừng vòng LISTEN và đóng kết nối."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self.connected.clear()

    async def _run(self) -> None:
        """Nghe kênh `aqi_events`; lỗi kết nối thì nghỉ 1 → 30 giây rồi nối lại và phát resync."""
        backoff, first = 1.0, True
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(_libpq_dsn(), autocommit=True) as conn:
                    await conn.execute(f"LISTEN {CHANNEL}")
                    self.connected.set()
                    backoff = 1.0
                    if not first:
                        self.publish_local({"type": "resync"})
                    first = False
                    async for note in conn.notifies():
                        try:
                            self.publish_local(json.loads(note.payload))
                        except ValueError:
                            log.warning("Bỏ sự kiện realtime không phải JSON")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — mất kết nối DB: thử lại
                log.warning("Mất kết nối LISTEN %s (%s); thử lại sau %.0f giây", CHANNEL, type(exc).__name__, backoff)
            self.connected.clear()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)


def _libpq_dsn() -> str:
    """DATABASE_URL dạng SQLAlchemy (`postgresql+psycopg://…`) → chuỗi kết nối psycopg."""
    return make_url(get_settings().database_url).set(drivername="postgresql").render_as_string(hide_password=False)


hub = EventHub()
