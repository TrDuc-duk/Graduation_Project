"""Cấu hình sửa trên Admin (`app_settings`, backend_design 15.2).

Giá trị mặc định nằm ở DEFAULTS; dòng trong DB (nếu có) ghi đè. Đọc có cache ngắn để không truy vấn mỗi request.
"""

import time
from typing import Any

from sqlalchemy import text

from app.core.db import get_sessionmaker

# Chỉ các khóa backend đã dùng tới; mốc sau bổ sung dần
DEFAULTS: dict[str, Any] = {
    "gateway_offline_after_s": 900,
    "default_node_offline_after_s": 3900,
    "gateway_flush_interval_s": 30,
    "gateway_heartbeat_interval_s": 300,
    "stale_gap_factor": 2,
    "stale_send_tolerance_s": 45,
    "max_msg_gap": 20,
    "address_quarantine_days": 30,
    "interval_max_iqr_ratio": 0.2,
    "telemetry_gateway_limit_per_min": 120,
    "telemetry_ip_error_limit_per_min": 20,
    "telemetry_global_limit_per_min": 6000,
    "pm_spike_delta": 100,
    "default_station_id": None,  # mã trạm mặc định (vd "ST001") cho Xiaozhi khi người dùng không nêu trạm
}

CACHE_TTL_S = 30

_cache: dict[str, Any] = {}
_loaded_at = 0.0


async def get(key: str) -> Any:
    """Giá trị hiện hành của một khóa: lấy từ DB nếu Admin đã đặt, không thì lấy mặc định."""
    await _refresh_if_stale()
    return _cache.get(key, DEFAULTS[key])


async def get_many(*keys: str) -> dict[str, Any]:
    """Lấy nhiều khóa một lần, trả dict {khóa: giá trị}."""
    return {k: await get(k) for k in keys}


def clear_cache() -> None:
    """Bỏ cache để lần đọc sau lấy lại từ DB (dùng khi vừa ghi, và trong test)."""
    global _loaded_at
    _cache.clear()
    _loaded_at = 0.0


async def _refresh_if_stale() -> None:
    """Đọc lại toàn bộ app_settings khi cache quá 30 giây."""
    global _loaded_at
    if time.monotonic() - _loaded_at < CACHE_TTL_S:
        return
    async with get_sessionmaker()() as session:
        rows = (await session.execute(text("SELECT key, value FROM app_settings"))).all()
    _cache.clear()
    _cache.update({r.key: r.value for r in rows})
    _loaded_at = time.monotonic()
