"""Gán thời điểm đo cho bản ghi (backend_design 6.6.2, 6.6.4). Thuần Python.

Firmware không gửi thời điểm đo; server chỉ biết lúc nhận batch T, nên ước lượng lùi về trước theo chu kỳ node.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.modules.telemetry.qc import QcFlag

MSG_ID_MAX_INTERVAL_S = 600  # node phát heartbeat sau 10 phút không có dữ liệu (LORA_QUEUE_TIMEOUT_MS)
MSG_ID_MAX_SPAN = 128  # tránh nhầm do bộ đếm 1 byte quay vòng


@dataclass
class TimeInput:
    """Phần của bản ghi cần để tính thời điểm: msg_id và có phải heartbeat node không."""

    msg_id: int | None
    is_heartbeat: bool


@dataclass
class TimeResult:
    """Thời điểm đo đã gán, nguồn thời điểm và cờ qc về thời gian."""

    measured_at: datetime
    time_source: str  # received | estimated | unreliable
    flags: int


def batch_max_age_s(
    now: datetime,
    stale: bool,
    prev_last_seen_at: datetime | None,
    prev_last_telemetry_at: datetime | None,
    *,
    flush_s: int,
    tolerance_s: int,
) -> int | None:
    """max_age_s: thời điểm đo thật nằm trong [T − max_age_s, T] (R6). None = không xác định.

    - Batch bình thường: (T − lần cuối thấy Gateway) + chu kỳ xả + dung sai.
    - Batch nghi cũ: T − lần nhận telemetry trước + dung sai.
    - Lần đầu nghe thấy Gateway: None.
    """
    if stale:
        if prev_last_telemetry_at is None:
            return None
        return int((now - prev_last_telemetry_at).total_seconds()) + tolerance_s
    if prev_last_seen_at is None:
        return None
    return int((now - prev_last_seen_at).total_seconds()) + flush_s + tolerance_s


def msg_steps(msg_ids: list[int]) -> list[int]:
    """Bước đếm giữa các msg_id liên tiếp, lấy modulo 256: [250, 255, 3] → [5, 4]."""
    return [(b - a) % 256 for a, b in zip(msg_ids, msg_ids[1:], strict=False)]


def can_use_msg_id(
    records: list[TimeInput],
    interval_s: int | None,
    now: datetime,
    prev_last_telemetry_at: datetime | None,
    stale: bool,
    max_msg_gap: int,
) -> bool:
    """Đủ cả 7 điều kiện để lùi thời gian theo msg_id (backend_design 6.6.4) thì True."""
    if stale or interval_s is None or interval_s >= MSG_ID_MAX_INTERVAL_S:
        return False
    if any(r.msg_id is None or r.is_heartbeat for r in records):
        return False
    steps = msg_steps([r.msg_id for r in records])  # type: ignore[misc]
    span = sum(steps)
    if not all(1 <= s <= max_msg_gap for s in steps) or span >= MSG_ID_MAX_SPAN:
        return False
    if prev_last_telemetry_at is None:  # không biết đã trôi bao lâu từ lần xả trước
        return False
    return span * interval_s <= (now - prev_last_telemetry_at).total_seconds() + interval_s


def assign_times(
    records: list[TimeInput],
    now: datetime,
    interval_s: int | None,
    *,
    prev_last_telemetry_at: datetime | None,
    stale: bool,
    max_msg_gap: int,
    max_age_s: int | None,
) -> list[TimeResult]:
    """Gán thời điểm đo cho các bản ghi của MỘT node trong batch (theo thứ tự seq, cũ → mới).

    - Batch nghi cũ: mọi bản = T, 'unreliable' + TIME_UNRELIABLE (T chỉ giữ chỗ).
    - Một bản: T, 'received'.
    - Nhiều bản, chưa biết chu kỳ: T cho tất cả + INTERVAL_UNKNOWN.
    - Nhiều bản, dùng được msg_id: T − (tổng bước từ bản i tới bản cuối) × chu kỳ.
    - Còn lại: T − (k − 1 − i) × chu kỳ.
    Ước lượng không bao giờ cũ hơn T − max_age_s và không bao giờ vượt T.
    """
    k = len(records)
    if stale:
        return [TimeResult(now, "unreliable", int(QcFlag.TIME_UNRELIABLE)) for _ in records]
    if k == 1:
        return [TimeResult(now, "received", 0)]
    if interval_s is None:
        return [TimeResult(now, "received", int(QcFlag.INTERVAL_UNKNOWN)) for _ in records]

    if can_use_msg_id(records, interval_s, now, prev_last_telemetry_at, stale, max_msg_gap):
        steps = msg_steps([r.msg_id for r in records])  # type: ignore[misc]
        steps_back = [sum(steps[i:]) for i in range(k)]
        extra = QcFlag.TIME_ESTIMATED | QcFlag.TIME_FROM_MSG_ID
    else:
        steps_back = [k - 1 - i for i in range(k)]
        extra = QcFlag.TIME_ESTIMATED

    oldest_allowed = now - timedelta(seconds=max_age_s) if max_age_s is not None else None
    results = []
    for back in steps_back:
        if back == 0:
            results.append(TimeResult(now, "received", 0))
            continue
        t = now - timedelta(seconds=back * interval_s)
        if oldest_allowed and t < oldest_allowed:
            t = oldest_allowed
        results.append(TimeResult(t, "estimated", int(extra)))
    return results
