"""Cấu hình sửa trên Admin (`app_settings`, backend_design 15.2).

Giá trị mặc định nằm ở DEFAULTS; dòng trong DB (nếu có) ghi đè. Đọc có cache ngắn để không truy vấn mỗi request.
"""

import time
from typing import Any

from sqlalchemy import text

from app.core.db import get_sessionmaker

# Đủ các khóa của backend_design 15.2; migration 0007_settings_seed chèn đúng các giá trị này vào DB
DEFAULTS: dict[str, Any] = {
    "public_horizons": list(range(3, 73, 3)),  # đủ 24 mốc 3–72 giờ (P6)
    "forecast_confidence": {"high": [3, 6], "medium": [9, 24], "low": [27, 72]},
    "hourly_min_samples": 1,  # P1, tạm thời
    "hour_close_grace_s": 180,
    "gateway_offline_after_s": 900,
    "default_node_offline_after_s": 3900,
    "gateway_flush_interval_s": 30,
    "gateway_heartbeat_interval_s": 300,
    "stale_gap_factor": 2,
    "stale_send_tolerance_s": 45,
    "max_msg_gap": 20,
    "telegram_enabled": True,
    "telegram_min_severity": "warning",
    "forecast_catchup_max_hours": 24,
    "forecast_late_after_s": 600,
    "sse_max_per_ip": 50,
    "sse_max_per_admin": 10,
    "sse_max_total": 1000,
    "sse_queue_size": 100,
    "disk_warn_pct": 70,
    "disk_critical_pct": 85,
    "address_quarantine_days": 30,
    "refresh_grace_s": 30,
    "forecast_stale_max_h": 6,
    "forecast_max_attempts": 3,
    "interval_max_iqr_ratio": 0.2,
    "telemetry_gateway_limit_per_min": 120,
    "telemetry_ip_error_limit_per_min": 20,
    "telemetry_global_limit_per_min": 6000,
    "default_station_id": None,  # mã trạm mặc định (vd "ST001") cho trang chủ và Xiaozhi khi không nêu trạm
    "pm_spike_delta": 100,
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
