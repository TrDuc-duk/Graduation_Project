"""Provisioning Gateway/node qua cổng thiết bị (backend_design 6.8, database_design 9)."""

import asyncio
from datetime import timedelta

from tests.conftest import T0
from tests.fixtures.firmware import PROVISION_KEY, provision_gateway, provision_node
from tests.integration.helpers import add_gateway, add_node, execute, rows, scalar

API = "/api/v1/provision"


async def test_provision_gateway_returns_201_and_firmware_reads_data_id(client, db):
    r = await client.post(f"{API}/gateway", json=provision_gateway())
    assert r.status_code == 201
    body = r.json()
    assert body["success"] is True
    assert body["data"] == {
        "id": "GW_001",
        "name": "Gateway Bách Khoa",
        "location_desc": "Tầng 3 nhà C1",
        "status": "pending",
    }
    r2 = await client.post(f"{API}/gateway", json=provision_gateway(name="GW thứ hai"))
    assert r2.json()["data"]["id"] == "GW_002"
    assert scalar(db, "SELECT registered_via FROM gateways WHERE id = 'GW_001'") == "provision"


async def test_provision_log_never_stores_key(client, db):
    await client.post(f"{API}/gateway", json=provision_gateway())
    [log] = rows(db, "SELECT kind, http_status, payload FROM ingest_batches")
    assert (log.kind, log.http_status) == ("provision", 201)
    assert "provision_key" not in log.payload and log.payload["name"] == "Gateway Bách Khoa"


async def test_list_gateways_only_active(client, db):
    add_gateway(db, "GW_001", status="active", location_desc="C1")
    add_gateway(db, "GW_002", status="pending")
    r = await client.get(f"{API}/gateways", params={"provision_key": PROVISION_KEY})
    assert r.status_code == 200
    assert r.json() == {
        "success": True,
        "data": [{"id": "GW_001", "name": "GW_001", "status": "active", "location_desc": "C1"}],
    }


async def test_provision_node_gets_lowest_free_address_and_station_code(client, db):
    add_gateway(db)
    r = await client.post(f"{API}/node", json=provision_node(lat=21.0285, lng=105.8542))
    assert r.status_code == 201
    data = r.json()["data"]
    assert (data["id"], data["node_numeric_id"], data["station_code"], data["status"]) == (
        "NODE_001",
        1,
        "ST001",
        "pending",
    )
    [node] = rows(db, "SELECT home_gateway_id, ST_X(geom) AS lng, ST_Y(geom) AS lat FROM nodes")
    assert (node.home_gateway_id, node.lng, node.lat) == ("GW_001", 105.8542, 21.0285)


async def test_provision_node_skips_used_and_quarantined_addresses(client, db, clock):
    add_gateway(db)
    add_node(db, 1)
    add_node(db, 2, status="retired", retired_at=T0 - timedelta(days=5))  # còn cách ly (30 ngày)
    add_node(db, 3, status="retired", retired_at=T0 - timedelta(days=40))  # hết cách ly → cấp lại được
    r = await client.post(f"{API}/node", json=provision_node())
    assert r.json()["data"]["node_numeric_id"] == 3


async def test_provision_node_409_when_network_full(client, db):
    add_gateway(db)
    execute(
        db,
        "INSERT INTO nodes (station_code, lora_network_id, lora_addr, name, registered_via) "
        "SELECT 'ST' || lpad(a::text, 3, '0'), 1, a, 'n', 'admin' FROM generate_series(1, 255) a",
    )
    r = await client.post(f"{API}/node", json=provision_node())
    assert r.status_code == 409 and r.json()["success"] is False


async def test_concurrent_node_provisioning_gets_different_addresses(client, db):
    add_gateway(db)
    results = await asyncio.gather(*(client.post(f"{API}/node", json=provision_node(name=f"n{i}")) for i in range(5)))
    assert sorted(r.json()["data"]["node_numeric_id"] for r in results) == [1, 2, 3, 4, 5]


async def test_provision_node_unknown_gateway_and_bad_coordinates(client, db):
    r = await client.post(f"{API}/node", json=provision_node(gateway_id="GW_404"))
    assert r.status_code == 400 and r.json()["error"] == "Gateway không tồn tại!"
    r = await client.post(f"{API}/node", json=provision_node(gateway_id=None, lat=21.0))
    assert r.status_code == 400


async def test_provision_node_without_gateway_uses_default_network(client, db):
    r = await client.post(f"{API}/node", json=provision_node(gateway_id=None))
    assert r.status_code == 201 and r.json()["data"]["gateway_id"] is None


async def test_provision_key_missing_401_wrong_403(client, db):
    r = await client.post(f"{API}/gateway", json={"name": "x"})
    assert r.status_code == 401 and r.json() == {"success": False, "error": "Thiếu mã xác thực (provision_key)"}
    r = await client.post(f"{API}/gateway", json={**provision_gateway(), "provision_key": "sai"})
    assert r.status_code == 403
    r = await client.get(f"{API}/gateways", params={"provision_key": "sai"})
    assert r.status_code == 403
    assert scalar(db, "SELECT count(*) FROM security_events WHERE kind = 'device_auth_failed'") == 3
    assert scalar(db, "SELECT count(*) FROM gateways") == 0


async def test_provision_rate_limit_10_per_minute(client, db):
    codes = [
        (await client.get(f"{API}/gateways", params={"provision_key": PROVISION_KEY})).status_code for _ in range(11)
    ]
    assert codes[:10] == [200] * 10 and codes[10] == 429
