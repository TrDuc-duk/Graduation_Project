"""Job interval_stats chạy trên dữ liệu đi qua API như Gateway thật gửi."""

from app.core.scheduler import run_job
from app.modules.ingest.jobs import interval_stats
from tests.fixtures.firmware import item, telemetry
from tests.integration.helpers import add_gateway, add_node, rows, scalar

URL = "/api/v1/telemetry"


async def send_every(client, clock, seconds: int, count: int, msg_start: int = 0, skip_msg: int = 1) -> None:
    """Gateway gửi `count` batch, mỗi batch một gói, cách nhau `seconds` giây."""
    for i in range(count):
        msg = (msg_start + i * skip_msg) % 256
        r = await client.post(URL, json=telemetry(items=[item(msg_id=msg, pm25=20.0 + i % 7)]))
        assert r.status_code == 200
        clock.advance(seconds=seconds)


async def test_interval_measured_from_25_batches(client, db, clock):
    add_gateway(db)
    add_node(db, 1)
    await send_every(client, clock, 15, 25)
    assert await run_job("interval_stats", interval_stats) == "ok"
    [node] = rows(db, "SELECT observed_interval_s, observed_interval_iqr_ratio, lost_packets_24h FROM nodes")
    assert (node.observed_interval_s, node.observed_interval_iqr_ratio, node.lost_packets_24h) == (15, 0.0, 0)
    assert scalar(db, "SELECT status FROM job_runs WHERE job = 'interval_stats'") == "ok"


async def test_lost_packets_counted_from_msg_id_gaps(client, db, clock):
    """Mỗi gói thứ hai bị mất trên đường LoRa: msg_id nhảy 2 → chu kỳ vẫn 15 giây, mất 24 gói."""
    add_gateway(db)
    add_node(db, 1)
    await send_every(client, clock, 30, 25, skip_msg=2)
    await interval_stats()
    [node] = rows(db, "SELECT observed_interval_s, lost_packets_24h FROM nodes")
    assert (node.observed_interval_s, node.lost_packets_24h) == (15, 24)


async def test_too_few_batches_leave_interval_unknown(client, db, clock):
    add_gateway(db)
    add_node(db, 1)
    await send_every(client, clock, 15, 10)
    await interval_stats()
    assert scalar(db, "SELECT observed_interval_s FROM nodes") is None
