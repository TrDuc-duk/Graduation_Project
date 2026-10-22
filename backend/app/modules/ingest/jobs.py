"""Job `interval_stats` (mỗi giờ): chu kỳ gửi đo được và số gói LoRa mất của node (backend_design 6.6.5).

Chỉ dùng thời điểm NHẬN của các batch (không bao giờ dùng measured_at ước lượng). Một quan sát là cặp batch
liên tiếp của cùng node qua CÙNG Gateway, cả hai không nghi cũ và không phải thử lại transaction.
"""

import statistics
from datetime import timedelta
from itertools import groupby

from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings_store, timeutil
from app.core.db import run_in_transaction
from app.modules.devices import service as devices
from app.modules.ingest.timing import MSG_ID_MAX_SPAN, msg_steps
from app.modules.telemetry import service as telemetry

MIN_OBSERVATIONS = 20
WINDOW = timedelta(hours=24)


def interval_observations(rows: list[Row], max_msg_gap: int) -> list[float]:
    """Các khoảng (giây/gói) quan sát được từ số đo đáng tin của một node, theo thứ tự nhận.

    - Có msg_id liên tục (mỗi bước 1…max_msg_gap, tổng < 128): khoảng = ΔT / span.
    - Không có msg_id: khoảng = ΔT / số bản ghi của node trong batch sau.
    - msg_id có nhưng bước bất thường (node khởi động lại): bỏ quan sát.
    Điều kiện "chu kỳ < 600 giây" của mục 6.6.4 không áp dụng ở đây vì chính chu kỳ đang được đo.
    """
    observations: list[float] = []
    for _, gw_rows in groupby(sorted(rows, key=lambda r: r.gateway_id), key=lambda r: r.gateway_id):
        batches = [list(b) for _, b in groupby(gw_rows, key=lambda r: (r.batch_id, r.received_at))]
        for prev, cur in zip(batches, batches[1:], strict=False):
            if not (_usable(prev) and _usable(cur)):
                continue
            delta = (cur[-1].received_at - prev[-1].received_at).total_seconds()
            if delta < 1:
                continue
            msg_ids = [prev[-1].msg_id] + [r.msg_id for r in cur]
            if all(m is None for m in msg_ids):
                observations.append(delta / len(cur))
            elif None not in msg_ids:
                steps = msg_steps(msg_ids)
                span = sum(steps)
                if all(1 <= s <= max_msg_gap for s in steps) and span < MSG_ID_MAX_SPAN:
                    observations.append(delta / span)
    return observations


def _usable(batch: list[Row]) -> bool:
    """Batch dùng được để đo chu kỳ: không nghi cũ, không thử lại, bản cuối của node mang thời điểm nhận."""
    last = batch[-1]
    return not last.stale_suspected and last.attempts == 1 and last.time_source == "received"


def summarize_interval(observations: list[float], max_iqr_ratio: float) -> tuple[int | None, float | None]:
    """(chu kỳ đo được, IQR/trung vị). Dưới 20 quan sát → (None, None); phân tán quá lớn → (None, tỷ lệ)."""
    if len(observations) < MIN_OBSERVATIONS:
        return None, None
    q1, median, q3 = statistics.quantiles(observations, n=4)
    ratio = (q3 - q1) / median if median > 0 else None
    if ratio is None or ratio > max_iqr_ratio:
        return None, ratio
    return round(median), ratio


def lost_packets(msg_ids: list[int | None], max_msg_gap: int) -> int | None:
    """Số gói mất = tổng (bước − 1) của các bước hợp lệ; bước 0 (gói trùng) hoặc quá lớn (khởi động lại) bỏ qua.

    Heartbeat node cũng chiếm msg_id nhưng không được lưu, nên có thể bị tính là mất (chấp nhận).
    """
    ids = [m for m in msg_ids if m is not None]
    if len(ids) < 2:
        return None
    return sum(s - 1 for s in msg_steps(ids) if 1 <= s <= max_msg_gap)


async def interval_stats() -> dict:
    """Job: cập nhật observed_interval_s, observed_interval_iqr_ratio, lost_packets_24h cho mọi node có dữ liệu."""
    since = timeutil.now() - WINDOW
    max_gap = await settings_store.get("max_msg_gap")
    max_ratio = await settings_store.get("interval_max_iqr_ratio")
    node_ids = await run_in_transaction(lambda s: telemetry.nodes_with_trusted_data(s, since))

    async def update_node(session: AsyncSession, node_id: int) -> None:
        rows = await telemetry.trusted_with_batch(session, node_id, since)
        observed, ratio = summarize_interval(interval_observations(rows, max_gap), max_ratio)
        lost = lost_packets([r.msg_id for r in rows], max_gap)
        await devices.set_interval_stats(session, node_id, observed, ratio, lost)

    for node_id in node_ids:  # mỗi node một transaction ngắn
        await run_in_transaction(lambda s, n=node_id: update_node(s, n))
    return {"nodes": len(node_ids)}
