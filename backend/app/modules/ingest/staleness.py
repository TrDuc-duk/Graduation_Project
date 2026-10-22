"""Phát hiện batch nghi chứa dữ liệu cũ (backend_design 6.6.3). Thuần Python."""

from datetime import datetime

GATEWAY_SILENT = "gateway_silent"
AFTER_REJECTION = "after_rejection"


def silence_threshold_s(c_min: int | None, *, heartbeat_s: int, flush_s: int, factor: float, tolerance_s: int) -> float:
    """Ngưỡng im lặng của Gateway = hệ số × nhịp kỳ vọng + dung sai.

    Nhịp kỳ vọng = min(heartbeat, max(chu kỳ xả, c_min)); không có c_min thì = heartbeat.
    Ví dụ node 15 giây → 2 × 30 + 45 = 105 giây; chỉ node 30 phút → 2 × 300 + 45 = 645 giây.
    """
    rhythm = heartbeat_s if c_min is None else min(heartbeat_s, max(flush_s, c_min))
    return factor * rhythm + tolerance_s


def check_stale(
    now: datetime,
    last_seen_at: datetime | None,
    rejected_since: datetime | None,
    c_min: int | None,
    *,
    heartbeat_s: int,
    flush_s: int,
    factor: float,
    tolerance_s: int,
) -> str | None:
    """Lý do batch bị nghi chứa dữ liệu cũ, hoặc None nếu bình thường.

    - after_rejection: server đã trả lỗi cho telemetry trước đó → firmware đang gửi lại dữ liệu bị giữ.
    - gateway_silent: Gateway im lặng lâu hơn ngưỡng → buffer có thể đã giữ dữ liệu từ lâu.
    Lần đầu nghe thấy Gateway (last_seen_at = None) thì không xét được, coi là bình thường.
    """
    if rejected_since is not None:
        return AFTER_REJECTION
    if last_seen_at is None:
        return None
    threshold = silence_threshold_s(
        c_min, heartbeat_s=heartbeat_s, flush_s=flush_s, factor=factor, tolerance_s=tolerance_s
    )
    return GATEWAY_SILENT if (now - last_seen_at).total_seconds() > threshold else None
