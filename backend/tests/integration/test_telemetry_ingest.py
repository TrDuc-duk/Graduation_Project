"""Hợp đồng firmware và quy tắc ingest (backend_design 6.2–6.7) với payload thật của datn-main."""

import asyncio
from datetime import timedelta

import pytest

from app.modules.ingest import pipeline
from app.modules.telemetry.qc import QcFlag
from tests.conftest import T0
from tests.fixtures.firmware import heartbeat, heartbeat_item, item, sensor_error_item, telemetry
from tests.integration.helpers import add_gateway, add_node, rows, scalar

URL = "/api/v1/telemetry"


@pytest.fixture
def active_setup(db, clock):
    """Gateway GW_001 đã duyệt và node NODE_001 đang hoạt động (như sau khi Admin duyệt)."""
    add_gateway(db)
    return add_node(db, 1)


def measurements(db):
    return rows(db, "SELECT * FROM measurements ORDER BY seq, received_at")


# ---------- hợp đồng cơ bản ----------


async def test_valid_batch_is_stored_and_returns_stats(client, db, active_setup):
    r = await client.post(URL, json=telemetry())
    assert r.status_code == 200
    assert r.json() == {"success": True, "accepted": 1, "duplicates": 0, "heartbeats": 0, "rejected": 0}

    [m] = measurements(db)
    assert (m.node_id, m.gateway_id, m.measured_at, m.received_at, m.time_source) == (
        active_setup,
        "GW_001",
        T0,
        T0,
        "received",
    )
    assert (m.pm25, m.pm10, m.co2, m.tvoc, m.temperature, m.humidity) == (70.0, 80.5, 800, 120, 32.5, 70.0)
    assert (m.battery_pct, m.msg_id, m.aqi_instant, m.qc_flags, m.trusted_at) == (92, 12, 158, 0, T0)
    assert m.max_age_s is None  # lần đầu nghe thấy Gateway

    [node] = rows(db, "SELECT * FROM nodes")
    assert (node.last_seen_at, node.last_heard_at, node.last_measurement_at, node.first_data_at) == (T0,) * 4
    assert (node.connectivity, node.battery_pct, node.last_msg_id, node.last_gateway_id) == ("online", 92, 12, "GW_001")
    assert {(s.sensor, s.health) for s in rows(db, "SELECT * FROM node_sensors")} == {
        ("pms7003", "ok"),
        ("aht10", "ok"),
        ("ccs811", "ok"),
    }
    [gw] = rows(db, "SELECT * FROM gateways")
    assert (gw.last_seen_at, gw.last_telemetry_at, gw.sends_msg_id, gw.connectivity) == (T0, T0, True, "online")

    [batch] = rows(db, "SELECT * FROM ingest_batches")
    assert (batch.kind, batch.http_status, batch.item_count, batch.accepted, batch.has_msg_id) == (
        "telemetry",
        200,
        1,
        1,
        True,
    )
    assert "secret" not in batch.payload
    [event] = rows(db, "SELECT kind, partition_key, payload FROM outbox_events")
    assert (event.kind, event.partition_key) == ("measurements_ingested", f"node:{active_setup}")
    assert event.payload["has_trusted"] is True and len(event.payload["measurement_ids"]) == 1


@pytest.mark.parametrize(("co2", "tvoc"), [(2359, 1477), (29206, 32768)])
async def test_ccs811_full_output_range_reaches_database(client, db, active_setup, co2, tvoc):
    response = await client.post(URL, json=telemetry(items=[item(co2=co2, tvoc=tvoc)]))
    assert response.status_code == 200 and response.json()["accepted"] == 1
    [reading] = measurements(db)
    assert (reading.co2, reading.tvoc, reading.qc_flags) == (co2, tvoc, 0)


async def test_resent_batch_is_duplicate(client, db, active_setup, clock):
    body = telemetry(items=[item(msg_id=1), item(msg_id=2, pm25=71.0)])
    await client.post(URL, json=body)
    clock.advance(seconds=30)
    r = await client.post(URL, json=body)  # server đã trả 200 nhưng phản hồi không tới Gateway
    assert r.json()["duplicates"] == 2 and r.json()["accepted"] == 0
    assert len(measurements(db)) == 2


async def test_node_heartbeat_is_not_stored_but_updates_state(client, db, active_setup):
    r = await client.post(URL, json=telemetry(items=[heartbeat_item(battery=55)]))
    assert r.json()["heartbeats"] == 1 and measurements(db) == []
    [node] = rows(db, "SELECT last_seen_at, battery_pct, last_measurement_at FROM nodes")
    assert (node.last_seen_at, node.battery_pct, node.last_measurement_at) == (T0, 55, None)


async def test_sensor_error_values_are_stored_as_null(client, db, active_setup):
    await client.post(URL, json=telemetry(items=[sensor_error_item()]))
    [m] = measurements(db)
    assert (m.pm25, m.co2, m.temperature, m.qc_flags) == (None, None, None, QcFlag.GAS_INVALID)
    assert {s.health for s in rows(db, "SELECT health FROM node_sensors")} == {"error"}


async def test_gateway_30pin_without_msg_id(client, db, active_setup):
    r = await client.post(URL, json=telemetry(items=[item(msg_id=None)]))
    assert r.json()["accepted"] == 1
    assert scalar(db, "SELECT sends_msg_id FROM gateways") is False
    assert measurements(db)[0].msg_id is None


async def test_ten_record_batch_without_interval_keeps_receive_time(client, db, active_setup):
    """Chưa biết chu kỳ node: mọi bản = T, cờ INTERVAL_UNKNOWN; measured_at được phép trùng nhau."""
    r = await client.post(URL, json=telemetry(items=[item(msg_id=i, pm25=10.0 + i) for i in range(10)]))
    assert r.json()["accepted"] == 10
    ms = measurements(db)
    assert {m.measured_at for m in ms} == {T0}
    assert all(m.qc_flags & QcFlag.INTERVAL_UNKNOWN for m in ms)


async def test_msg_id_backoff_with_known_interval(client, db, clock):
    add_gateway(db)
    add_node(db, 1, expected_interval_s=10)
    await client.post(URL, json=telemetry(items=[item(msg_id=253)]))
    clock.advance(seconds=30)
    await client.post(URL, json=telemetry(items=[item(msg_id=254), item(msg_id=255), item(msg_id=0)]))
    latest = rows(
        db,
        "SELECT measured_at, time_source, qc_flags FROM measurements WHERE received_at = :t ORDER BY seq",
        t=clock.at,
    )
    assert [clock.at - m.measured_at for m in latest] == [timedelta(seconds=20), timedelta(seconds=10), timedelta(0)]
    assert latest[0].qc_flags == QcFlag.TIME_ESTIMATED | QcFlag.TIME_FROM_MSG_ID
    assert latest[2].time_source == "received"


# ---------- thiết bị lạ, cách ly (6.3) ----------


async def test_unknown_gateway_and_node_are_created_pending_and_quarantined(client, db, clock):
    r = await client.post(URL, json=telemetry(gateway_id="GW_013", items=[item(node=76)]))
    assert r.json()["accepted"] == 1
    [gw] = rows(db, "SELECT status, registered_via FROM gateways")
    [node] = rows(db, "SELECT * FROM nodes")
    assert (gw.status, gw.registered_via) == ("pending", "auto_discovered")
    assert (node.device_code, node.status, node.registered_via, node.station_code) == (
        "NODE_076",
        "pending",
        "auto_discovered",
        "ST001",
    )
    [m] = measurements(db)
    assert m.qc_flags & QcFlag.UNTRUSTED_GATEWAY and m.trusted_at is None
    # Qua Gateway chưa duyệt: không cập nhật trạng thái node (6.4.1)
    assert (node.last_seen_at, node.last_heard_at, node.battery_pct) == (None, None, None)
    assert scalar(db, "SELECT count(*) FROM security_events WHERE kind = 'device_discovered'") == 2


async def test_unknown_node_via_active_gateway_is_trusted(client, db, clock):
    add_gateway(db)
    await client.post(URL, json=telemetry(items=[item(node=9)]))
    [node] = rows(db, "SELECT status, last_seen_at FROM nodes")
    assert (node.status, node.last_seen_at) == ("pending", T0)
    assert measurements(db)[0].qc_flags == 0


async def test_retired_address_rejected_during_quarantine_then_reused(client, db, clock):
    add_gateway(db)
    old_id = add_node(db, 5, status="retired", retired_at=T0 - timedelta(days=10))
    r = await client.post(URL, json=telemetry(items=[item(node=5)]))
    assert r.status_code == 200 and r.json()["rejected"] == 1
    assert "retired_address" in scalar(db, "SELECT error FROM ingest_batches")

    clock.advance(days=21)  # hết 30 ngày cách ly
    r = await client.post(URL, json=telemetry(items=[item(node=5, msg_id=40)]))
    assert r.json()["accepted"] == 1
    new_id = scalar(db, "SELECT id FROM nodes WHERE status = 'pending'")
    assert new_id != old_id and measurements(db)[0].node_id == new_id


async def test_bad_node_id_and_inactive_gateway_are_rejected_with_200(client, db, clock):
    add_gateway(db)
    r = await client.post(URL, json=telemetry(items=[item(), {**item(), "node_id": "NODE_7"}]))
    assert r.json() == {"success": True, "accepted": 1, "duplicates": 0, "heartbeats": 0, "rejected": 1}

    add_gateway(db, "GW_002", status="retired", retired_at=T0)
    r = await client.post(URL, json=telemetry(gateway_id="GW_002", items=[item(node=3)]))
    assert r.status_code == 200 and r.json()["rejected"] == 1


# ---------- chống trùng giữa các Gateway (R4) ----------


async def test_active_gateway_copy_supersedes_pending_copy(client, db, clock):
    add_gateway(db, "GW_001", status="active")
    add_gateway(db, "GW_002", status="pending")
    node_id = add_node(db, 1)
    await client.post(URL, json=telemetry(gateway_id="GW_002"))  # bản qua Gateway chưa duyệt đến trước
    clock.advance(seconds=5)
    r = await client.post(URL, json=telemetry(gateway_id="GW_001"))
    assert r.json()["accepted"] == 1
    old, new = rows(db, "SELECT gateway_id, qc_flags, superseded_at FROM measurements ORDER BY received_at")
    assert old.gateway_id == "GW_002" and old.qc_flags & QcFlag.SUPERSEDED and old.superseded_at == clock.at
    assert new.gateway_id == "GW_001" and new.superseded_at is None
    assert scalar(db, "SELECT superseded FROM ingest_batches WHERE gateway_id = 'GW_001'") == 1
    links = rows(db, "SELECT gateway_id FROM node_gateway_links WHERE node_id = :n ORDER BY 1", n=node_id)
    assert [link.gateway_id for link in links] == ["GW_001", "GW_002"]


async def test_pending_copy_after_active_copy_is_duplicate(client, db, clock):
    add_gateway(db, "GW_001", status="active")
    add_gateway(db, "GW_002", status="pending")
    add_node(db, 1)
    await client.post(URL, json=telemetry(gateway_id="GW_001"))
    r = await client.post(URL, json=telemetry(gateway_id="GW_002"))
    assert r.json()["duplicates"] == 1 and len(measurements(db)) == 1


async def test_concurrent_batches_create_one_node_and_leave_no_locks(client, db):
    add_gateway(db, "GW_001")
    add_gateway(db, "GW_002")
    bodies = [telemetry(gateway_id=g, items=[item(node=77, msg_id=i)]) for i, g in enumerate(["GW_001", "GW_002"] * 3)]
    results = await asyncio.gather(*(client.post(URL, json=b) for b in bodies))
    assert all(r.status_code == 200 for r in results)
    assert scalar(db, "SELECT count(*) FROM nodes") == 1
    assert scalar(db, "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory'") == 0


# ---------- batch nghi cũ (6.6.3) ----------


async def test_batch_after_rejection_is_unreliable(client, db, active_setup, clock):
    await client.post(URL, json=telemetry(items=[item(msg_id=1)]))
    clock.advance(seconds=30)
    r = await client.post(URL, json=telemetry(items=[item(msg_id=i) for i in range(51)]))  # > 50 bản ghi
    assert r.status_code == 413
    assert scalar(db, "SELECT telemetry_rejected_since FROM gateways") == clock.at

    clock.advance(seconds=30)
    await client.post(URL, json=telemetry(items=[item(msg_id=2, pm25=99.0, pm10=120.0, battery=10)]))
    m = measurements(db)[-1]
    assert (m.time_source, m.measured_at, m.qc_flags) == ("unreliable", clock.at, QcFlag.TIME_UNRELIABLE)
    [batch] = rows(db, "SELECT stale_reason, possible_age_s FROM ingest_batches WHERE accepted = 1 AND stale_suspected")
    assert (batch.stale_reason, batch.possible_age_s) == ("after_rejection", 60 + 45)
    [gw] = rows(db, "SELECT telemetry_rejected_since FROM gateways")
    assert gw.telemetry_rejected_since is None
    # Node chỉ cập nhật last_heard_at; pin và last_seen_at giữ theo bản ghi đáng tin trước đó
    [node] = rows(db, "SELECT last_heard_at, last_seen_at, battery_pct FROM nodes")
    assert (node.last_heard_at, node.last_seen_at, node.battery_pct) == (clock.at, T0, 92)


async def test_batch_after_gateway_silence_is_unreliable(client, db, clock):
    add_gateway(db)
    add_node(db, 1, expected_interval_s=15)
    await client.post(URL, json=telemetry(items=[item(msg_id=1)]))
    clock.advance(seconds=106)  # ngưỡng im lặng với node 15 giây = 105 giây
    await client.post(URL, json=telemetry(items=[item(msg_id=2)]))
    assert scalar(db, "SELECT stale_reason FROM ingest_batches ORDER BY received_at DESC LIMIT 1") == "gateway_silent"


# ---------- cờ PM_SPIKE ----------


async def test_pm_spike_marked_against_previous_trusted_sample(client, db, active_setup, clock):
    await client.post(URL, json=telemetry(items=[item(msg_id=1, pm25=20.0, pm10=30.0)]))
    clock.advance(seconds=30)
    await client.post(URL, json=telemetry(items=[item(msg_id=2, pm25=150.0, pm10=160.0)]))
    assert measurements(db)[-1].qc_flags & QcFlag.PM_SPIKE


# ---------- mã lỗi, bảo mật (6.2, 14) ----------


async def test_wrong_or_missing_secret_is_401(client, db, active_setup):
    r = await client.post(URL, json=telemetry(secret="sai"))
    assert r.status_code == 401 and r.json()["success"] is False
    r = await client.post(URL, json={"gateway_id": "GW_001", "data": [item()]})
    assert r.status_code == 401
    assert scalar(db, "SELECT count(*) FROM security_events WHERE kind = 'device_auth_failed'") == 2
    assert scalar(db, "SELECT count(*) FROM ingest_batches WHERE http_status = 401") == 2
    assert measurements(db) == []


@pytest.mark.parametrize(
    "body",
    [b"not json", b'{"gateway_id": "GW_001", "secret": "super-secret-key", "data": {}}', b"[1]"],
)
async def test_malformed_body_is_400(client, db, body):
    r = await client.post(URL, content=body, headers={"content-type": "application/json"})
    assert r.status_code == 400
    assert r.json()["success"] is False


async def test_body_over_32kb_is_413(client, db):
    r = await client.post(URL, json=telemetry(items=[item(node_id="NODE_001" + " " * 40000)]))
    assert r.status_code == 413


async def test_21_bad_secrets_per_minute_from_one_ip_get_429(client, db):
    codes = [(await client.post(URL, json=telemetry(secret="sai"))).status_code for _ in range(21)]
    assert codes[:20] == [401] * 20 and codes[20] == 429


async def test_gateway_limit_120_per_minute_then_429_marks_rejection(client, db, active_setup):
    for i in range(120):
        assert (await client.post(URL, json=telemetry(items=[item(msg_id=i % 256)]))).status_code == 200
    r = await client.post(URL, json=telemetry())
    assert r.status_code == 429
    assert scalar(db, "SELECT telemetry_rejected_since FROM gateways") is not None


async def test_many_known_gateways_from_one_ip_are_not_limited(client, db):
    for g in range(1, 31):
        add_gateway(db, f"GW_{g:03d}")
    codes = {(await client.post(URL, json=telemetry(gateway_id=f"GW_{g:03d}"))).status_code for g in range(1, 31)}
    assert codes == {200}


async def test_db_failure_returns_503_and_marks_rejection(client, db, active_setup, monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("DB down")

    monkeypatch.setattr(pipeline, "ingest_telemetry", broken)
    r = await client.post(URL, json=telemetry())
    assert r.status_code == 503
    assert scalar(db, "SELECT telemetry_rejected_since FROM gateways") == T0
    assert scalar(db, "SELECT http_status FROM ingest_batches") == 503


# ---------- heartbeat Gateway ----------


async def test_gateway_heartbeat(client, db, clock):
    add_gateway(db, last_ip="10.0.0.9")
    r = await client.post(f"{URL}/heartbeat", json=heartbeat())
    assert r.status_code == 200 and r.json() == {"success": True, "message": "Heartbeat OK"}
    [gw] = rows(db, "SELECT last_heartbeat_at, last_seen_at, connectivity FROM gateways")
    assert (gw.last_heartbeat_at, gw.last_seen_at, gw.connectivity) == (T0, T0, "online")
    assert scalar(db, "SELECT kind FROM ingest_batches") == "heartbeat"
    assert scalar(db, "SELECT count(*) FROM security_events WHERE kind = 'gateway_ip_changed'") == 1


async def test_heartbeat_wrong_secret_and_unknown_gateway(client, db):
    assert (await client.post(f"{URL}/heartbeat", json=heartbeat(secret="sai"))).status_code == 401
    assert (await client.post(f"{URL}/heartbeat", json=heartbeat("GW_050"))).status_code == 200
    assert scalar(db, "SELECT status FROM gateways WHERE id = 'GW_050'") == "pending"


async def test_counts_add_up(client, db, active_setup):
    items = [item(msg_id=1), item(msg_id=1), heartbeat_item(), {**item(), "node_id": "BAD"}]
    r = (await client.post(URL, json=telemetry(items=items))).json()
    assert (r["accepted"], r["duplicates"], r["heartbeats"], r["rejected"]) == (1, 1, 1, 1)
