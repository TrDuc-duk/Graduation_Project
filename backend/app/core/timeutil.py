"""Thời gian dùng chung. Mọi chỗ lấy "bây giờ" qua now() để test giả lập được (backend_modules 5)."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


class Clock:
    """Đồng hồ thật: trả thời điểm hiện tại theo UTC."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock(Clock):
    """Đồng hồ giả cho test: đứng yên ở một thời điểm, tua tới bằng advance()."""

    def __init__(self, at: datetime):
        self.at = at

    def now(self) -> datetime:
        return self.at

    def advance(self, **kwargs: float) -> datetime:
        """Tua đồng hồ, ví dụ advance(seconds=30); trả thời điểm mới."""
        self.at += timedelta(**kwargs)
        return self.at


_clock: Clock = Clock()


def now() -> datetime:
    """Thời điểm hiện tại (UTC, có múi giờ) theo đồng hồ đang dùng."""
    return _clock.now()


def set_clock(clock: Clock) -> None:
    """Thay đồng hồ (chỉ dùng trong test)."""
    global _clock
    _clock = clock


def floor_hour(t: datetime) -> datetime:
    """Cắt về đầu giờ: 14:37:05 → 14:00:00."""
    return t.replace(minute=0, second=0, microsecond=0)


def to_local(t: datetime) -> datetime:
    """Đổi thời điểm UTC sang giờ Việt Nam để hiển thị."""
    return t.astimezone(LOCAL_TZ)
