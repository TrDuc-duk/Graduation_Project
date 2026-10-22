"""Test thuần Python của job interval_stats (backend_design 6.6.5)."""

from datetime import timedelta
from types import SimpleNamespace

from app.modules.ingest.jobs import interval_observations, lost_packets, summarize_interval
from tests.conftest import T0


def row(batch, seconds, msg_id=None, gateway="GW_001", seq=0, stale=False, attempts=1, source="received"):
    """Một số đo đáng tin như truy vấn trusted_with_batch trả về."""
    return SimpleNamespace(
        gateway_id=gateway,
        batch_id=batch,
        received_at=T0 + timedelta(seconds=seconds),
        seq=seq,
        msg_id=msg_id,
        time_source=source,
        stale_suspected=stale,
        attempts=attempts,
    )


def test_observations_with_msg_id_divide_by_span():
    """Batch 30 giây/lần, mỗi batch 2 gói (msg_id liên tục) → 15 giây/gói."""
    rows = [
        row(1, 0, 1, seq=0, source="estimated"),
        row(1, 0, 2, seq=1),
        row(2, 30, 3, seq=0, source="estimated"),
        row(2, 30, 4, seq=1),
    ]
    assert interval_observations(rows, 20) == [15.0]


def test_observations_without_msg_id_divide_by_count():
    rows = [row(1, 0), row(2, 30, seq=0, source="estimated"), row(2, 30, seq=1)]
    assert interval_observations(rows, 20) == [15.0]


def test_observations_skip_stale_retried_other_gateway_and_restart():
    rows = [row(1, 0, 1), row(2, 30, 2, stale=True), row(3, 60, 3)]
    assert interval_observations(rows, 20) == []  # cặp nào cũng có batch nghi cũ
    rows = [row(1, 0, 1), row(2, 30, 2, attempts=2)]
    assert interval_observations(rows, 20) == []
    rows = [row(1, 0, 1, gateway="GW_001"), row(2, 30, 2, gateway="GW_002")]
    assert interval_observations(rows, 20) == []  # khác Gateway → không ghép
    rows = [row(1, 0, 200), row(2, 30, 3)]
    assert interval_observations(rows, 20) == []  # bước 59 > 20: node khởi động lại


def test_summarize_needs_20_stable_observations():
    assert summarize_interval([15.0] * 19, 0.2) == (None, None)
    assert summarize_interval([15.0] * 20, 0.2) == (15, 0.0)
    observed, ratio = summarize_interval([5.0, 30.0] * 10, 0.2)
    assert observed is None and ratio > 0.2


def test_lost_packets():
    assert lost_packets([1, 2, 5, 6], 20) == 2  # mất 3, 4
    assert lost_packets([250, 3], 20) == 8  # quay vòng: bước 9
    assert lost_packets([10, 10, 200], 20) == 0  # gói trùng và khởi động lại không tính
    assert lost_packets([None, None], 20) is None
