"""Giới hạn số kết nối SSE (backend_design 14.2, R12): theo IP và toàn tiến trình, đọc từ app_settings."""

from collections import Counter

from app.core import settings_store

_by_ip: Counter[str] = Counter()
_total = 0


async def try_acquire(ip: str | None) -> bool:
    """Giữ một chỗ kết nối cho `ip`; False nếu đã đủ `sse_max_per_ip` hoặc `sse_max_total`."""
    global _total
    limits = await settings_store.get_many("sse_max_per_ip", "sse_max_total")
    key = ip or "?"
    if _total >= limits["sse_max_total"] or _by_ip[key] >= limits["sse_max_per_ip"]:
        return False
    _by_ip[key] += 1
    _total += 1
    return True


def release(ip: str | None) -> None:
    """Trả chỗ kết nối khi stream đóng (gọi trong finally)."""
    global _total
    key = ip or "?"
    if _by_ip[key] > 0:
        _by_ip[key] -= 1
        _total -= 1
        if _by_ip[key] == 0:
            del _by_ip[key]


def current() -> dict:
    """Số kết nối đang mở (cho test và trang Hệ thống)."""
    return {"total": _total, "by_ip": dict(_by_ip)}
