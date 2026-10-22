"""Module stations trên DB thật: trạm công khai, trạm mặc định, số đo hiện tại tin cậy, tóm tắt."""

from app.core import settings_store
from app.core.db import run_in_transaction
from app.modules.stations import service as stations
from tests.fixtures.firmware import item, telemetry
from tests.integration.helpers import add_gateway, add_node, execute


async def ingest(client, gateway_id: str = "GW_001", **kw) -> None:
    """Gửi một batch như Gateway thật."""
    r = await client.post("/api/v1/telemetry", json=telemetry(gateway_id=gateway_id, items=[item(**kw)]))
    assert r.status_code == 200


def set_default(db, code: str) -> None:
    execute(
        db, "INSERT INTO app_settings (key, value) VALUES ('default_station_id', to_jsonb(CAST(:c AS text)))", c=code
    )


async def test_only_active_public_nodes_are_stations(db):
    add_node(db, 1, name="Bách Khoa")
    add_node(db, 2, status="pending", name="Chờ duyệt")
    add_node(db, 3, name="Ẩn", is_public=False)
    add_node(db, 4, status="maintenance", name="Bảo trì")
    names = [n.name for n in await run_in_transaction(stations.list_public)]
    assert names == ["Bách Khoa"]


async def test_pending_station_cannot_be_resolved(db):
    add_node(db, 1, status="pending", name="Bách Khoa")
    assert await run_in_transaction(lambda s: stations.resolve_ref(s, "ST001")) == stations.NotFound("ST001")


async def test_default_station(db):
    add_node(db, 1, name="Bách Khoa")
    add_node(db, 2, status="pending", name="Chờ duyệt")
    resolve = lambda s: stations.resolve_ref(s, "default")  # noqa: E731
    assert isinstance(await run_in_transaction(resolve), stations.DefaultNotSet)
    set_default(db, "ST002")  # trạm chưa duyệt: coi như chưa đặt
    assert isinstance(await run_in_transaction(resolve), stations.DefaultNotSet)
    execute(db, "UPDATE app_settings SET value = to_jsonb(CAST('st001' AS text))")
    settings_store.clear_cache()  # bỏ cache 30 giây để đọc giá trị vừa sửa
    found = await run_in_transaction(resolve)
    assert isinstance(found, stations.Found) and found.node.station_code == "ST001"


async def test_latest_trusted_skips_quarantined_reading(client, db, clock):
    add_gateway(db)
    node_id = add_node(db, 1)
    await ingest(client, msg_id=1, pm25=30.0)
    clock.advance(seconds=30)
    await ingest(client, gateway_id="GW_013", msg_id=2, pm25=300.0)  # Gateway lạ: cách ly
    latest = await run_in_transaction(lambda s: stations.latest_trusted(s, node_id))
    assert latest.pm25 == 30.0


async def test_summary_over_real_ingest(client, db, clock):
    add_gateway(db)
    node_id = add_node(db, 1)
    for i, pm in enumerate([20.0, 22.0, 30.0, 45.0, 50.0, 55.0]):
        await ingest(client, msg_id=i, pm25=pm, pm10=pm + 10)
        clock.advance(minutes=10)
    s = await run_in_transaction(lambda session: stations.summary(session, node_id, 24, clock.now()))
    assert s.n_samples == 6 and s.metrics["pm25"].min == 20.0 and s.metrics["pm25"].max == 55.0
    assert s.metrics["pm25"].trend == stations.INCREASING
    assert s.metrics["aqi"].n == 6
