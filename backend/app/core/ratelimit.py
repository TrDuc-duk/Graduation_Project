"""Giới hạn tần suất trong bộ nhớ tiến trình (backend_design 14.2), dùng thư viện `limits`.

Chỉ đúng khi chạy một tiến trình API (RATE_LIMIT_BACKEND=memory, API_PROCESSES=1).
"""

from limits import RateLimitItemPerMinute
from limits.aio.storage import MemoryStorage
from limits.aio.strategies import MovingWindowRateLimiter

_storage = MemoryStorage()
_limiter = MovingWindowRateLimiter(_storage)


async def hit(key: str, per_minute: int) -> bool:
    """Đếm một lần cho `key`; trả False nếu đã vượt `per_minute` lần trong 60 giây gần nhất."""
    return await _limiter.hit(RateLimitItemPerMinute(per_minute), key)


async def reset() -> None:
    """Xóa mọi bộ đếm (dùng trong test)."""
    await _storage.reset()
