"""Chống trùng theo payload_hash + cửa sổ thời gian, chọn bản giữ lại theo thứ hạng (backend_design 6.5).

Thuần Python; truy vấn bản sao nằm ở telemetry.
"""

import hashlib

from app.modules.ingest.schemas import TelemetryItem
from app.modules.telemetry.qc import QcFlag

HASH_FIELDS = ("pm25", "pm10", "co2", "tvoc", "temperature", "humidity", "battery", "msg_id")

WINDOW_WITH_MSG_ID_S = 3600
WINDOW_MIN_S, WINDOW_MAX_S = 60, 900


def _fmt(v: float | int | None) -> str:
    """Chuẩn hóa một giá trị trước khi băm: số làm tròn 1 chữ số thập phân, null → 'null' (70 và 70.0 như nhau)."""
    return "null" if v is None else f"{round(float(v), 1):.1f}"


def payload_hash(item: TelemetryItem) -> int:
    """64 bit đầu BLAKE2b của 'node_id|pm25|pm10|co2|tvoc|temperature|humidity|battery|msg_id', dạng bigint có dấu."""
    text = "|".join([item.node_id, *(_fmt(getattr(item, f)) for f in HASH_FIELDS)])
    digest = hashlib.blake2b(text.encode(), digest_size=8).digest()
    return int.from_bytes(digest, "big", signed=True)


def window_s(has_msg_id: bool, interval_s: int | None) -> int:
    """Cửa sổ W (giây) để coi hai bản cùng hash là trùng: có msg_id 3600; không có thì nửa chu kỳ, kẹp 60–900."""
    if has_msg_id:
        return WINDOW_WITH_MSG_ID_S
    if interval_s is None:
        return WINDOW_MIN_S
    return int(min(max(interval_s / 2, WINDOW_MIN_S), WINDOW_MAX_S))


def rank(flags: int) -> tuple[bool, bool]:
    """Hạng của một bản sao, so sánh như tuple (lớn hơn = tốt hơn).

    Ưu tiên 1: qua Gateway active (không UNTRUSTED_GATEWAY). Ưu tiên 2: thời điểm tin cậy (không TIME_UNRELIABLE).
    Bằng hạng thì bản đến trước thắng, nên bản mới chỉ thay được bản cũ khi hạng cao hơn hẳn.
    """
    return (not flags & QcFlag.UNTRUSTED_GATEWAY, not flags & QcFlag.TIME_UNRELIABLE)
