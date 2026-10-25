"""Kênh SSE công khai `/api/v1/stream/public?station_id=` (backend_design 11.6).

Sự kiện đến từ `pg_notify('aqi_events')` qua EventHub. Mỗi client có hàng đợi hữu hạn, ping 15 giây, gửi chậm quá
10 giây thì đóng. Chỉ phát trạm đang công khai (kiểm tra lại khi phát) và chỉ các trường trong danh sách cho phép.
Không phát lại sự kiện cũ: client kết nối lại thì tải lại qua REST.
"""

import json
import time
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, Request
from sse_starlette import EventSourceResponse

from app.core import settings_store, timeutil
from app.core.db import run_in_transaction
from app.core.errors import AppError
from app.core.events import hub
from app.core.i18n import pick_language, t
from app.core.ratelimit import client_ip
from app.modules.devices import service as devices
from app.modules.realtime import limits
from app.modules.realtime.hub_client import ClientQueue

router = APIRouter(prefix="/stream", tags=["stream"])

PING_S = 15
SEND_TIMEOUT_S = 10
PUBLIC_CODES_TTL_S = 10  # trạm bị ẩn/ngưng hoạt động thì sau tối đa 10 giây không còn sự kiện
# Trường được phép ra kênh công khai theo loại sự kiện: {tên trong NOTIFY: tên trên SSE}
PUBLIC_FIELDS = {
    "measurement": {"measured_at": "measured_at", "pm25": "pm25", "pm10": "pm10", "aqi": "aqi_instant"},
    "hourly": {"hour_end": "hour_end", "aqi": "aqi", "level": "level"},
    "forecast": {"input_hour": "input_hour", "issued_at": "issued_at", "status": "status"},
    "station_status": {"online": "online"},
}
_TIME_FIELDS = ("measured_at", "hour_end", "input_hour", "issued_at")

_public_cache: tuple[float, frozenset[str]] = (0.0, frozenset())


def to_public(event: dict) -> dict | None:
    """Chuẩn hóa sự kiện nội bộ `{type, station_code, node_id, data}` thành dạng công khai; không cho phép → None."""
    kind = event.get("type")
    if kind == "resync":
        return {"type": "resync"}
    fields = PUBLIC_FIELDS.get(kind)
    code = event.get("station_code")
    if fields is None or not code:
        return None
    data = event.get("data") or {}
    out = {"type": kind, "station_id": code}
    for src, dst in fields.items():
        if src in data:
            out[dst] = _iso(data[src]) if src in _TIME_FIELDS else data[src]
    return out


@router.get("/public")
async def stream_public(
    request: Request, station_id: Annotated[str | None, Query(max_length=16)] = None
) -> EventSourceResponse:
    """Sự kiện `measurement`, `hourly`, `forecast`, `station_status` (lọc theo trạm nếu có `station_id`), `resync`."""
    ip = client_ip(request)
    if not await limits.try_acquire(ip):
        lang = pick_language(request.query_params.get("lang"), request.headers.get("accept-language"))
        raise AppError("SSE_LIMIT", 429, t("errors.SSE_LIMIT", lang))
    wanted = station_id.strip().upper() if station_id else None
    queue = ClientQueue(await settings_store.get("sse_queue_size"))

    def on_event(event: dict) -> None:
        public = to_public(event)
        if public is not None and (wanted is None or public["type"] == "resync" or public["station_id"] == wanted):
            queue.offer(public)

    unsubscribe = hub.subscribe(on_event)

    async def events():
        try:
            yield {"event": "ready", "data": "{}"}
            while True:
                event = await queue.get()
                if event["type"] != "resync" and event["station_id"] not in await _public_codes():
                    continue
                yield {"event": event["type"], "data": json.dumps(event, ensure_ascii=False)}
        finally:
            unsubscribe()
            limits.release(ip)

    return EventSourceResponse(
        events(),
        ping=PING_S,
        send_timeout=SEND_TIMEOUT_S,
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
    )


async def _public_codes() -> frozenset[str]:
    """Mã các trạm đang công khai (active, is_public, có tọa độ), cache 10 giây."""
    global _public_cache
    expires, codes = _public_cache
    if time.monotonic() >= expires:
        rows = await run_in_transaction(devices.public_points)
        codes = frozenset(r.Node.station_code for r in rows)
        _public_cache = (time.monotonic() + PUBLIC_CODES_TTL_S, codes)
    return codes


def clear_public_cache() -> None:
    """Bỏ cache trạm công khai (dùng trong test)."""
    global _public_cache
    _public_cache = (0.0, frozenset())


def _iso(value: object) -> object:
    """Thời điểm dạng chuỗi/datetime → ISO +07:00; giá trị khác giữ nguyên."""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    return timeutil.iso_local(value) if isinstance(value, datetime) and value.tzinfo else value
