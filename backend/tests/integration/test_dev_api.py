"""API dev chỉ đọc cho dashboard: /api/v1/dev/nodes, /api/v1/dev/nodes/{id}/readings."""

from httpx import ASGITransport, AsyncClient

from app import api
from app.core.config import Settings
from app.main import create_app
from app.modules.ingest.normalize import instant_aqi
from tests.fixtures.firmware import item, sensor_error_item, telemetry
from tests.integration.helpers import add_gateway, add_node, rows

URL = "/api/v1/dev/nodes"


async def ingest(client, **kw) -> None:
    """Gửi một batch như Gateway thật (đường ingest đầy đủ)."""
    r = await client.post("/api/v1/telemetry", json=telemetry(**kw))
    assert r.status_code == 200


async def test_lists_pending_node_with_gateway_and_freshness(client, db, clock):
    """Node tự phát hiện (pending) vẫn hiện ở API dev, kèm Gateway và độ mới."""
    add_gateway(db)
    await ingest(client, items=[item(node=76)])
    clock.advance(seconds=20)
    [node] = (await client.get(URL)).json()
    assert (node["device_code"], node["status"], node["station_code"]) == ("NODE_076", "pending", "ST001")
    assert node["gateway"]["id"] == "GW_001" and node["gateway"]["online"] is True
    assert (node["latest"]["pm25"], node["latest"]["aqi_instant"]) == (70.0, 158)
    assert node["freshness"] == {
        "last_received_at": "2026-10-15T07:00:00Z",
        "age_s": 20,
        "stale_after_s": 3900,
        "is_stale": False,
    }


async def test_readings_keep_null_and_units(client, db, clock):
    add_gateway(db)
    node_id = add_node(db, 1)
    await ingest(client, items=[item(msg_id=1)])
    clock.advance(seconds=30)
    await ingest(client, items=[sensor_error_item(msg_id=2)])
    body = (await client.get(f"{URL}/{node_id}/readings", params={"hours": 1})).json()
    assert body["units"]["pm25"] == "µg/m³" and body["units"]["co2"] == "ppm" and body["units"]["tvoc"] == "ppb"
    first, second = body["readings"]
    assert (first["pm25"], first["aqi_instant"], first["quarantined"]) == (70.0, 158, False)
    assert (second["pm25"], second["co2"], second["temperature"], second["aqi_instant"]) == (None, None, None, None)
    assert body["latest"]["received_at"] == second["received_at"]


async def test_range_filter_and_latest_outside_range(client, db, clock):
    """Số đo cũ hơn khoảng không nằm trong readings, nhưng vẫn là latest; quá ngưỡng thì dữ liệu cũ."""
    add_gateway(db)
    node_id = add_node(db, 1)
    await ingest(client)
    clock.advance(hours=2)
    one_hour = (await client.get(f"{URL}/{node_id}/readings", params={"hours": 1})).json()
    six_hours = (await client.get(f"{URL}/{node_id}/readings", params={"hours": 6})).json()
    assert one_hour["readings"] == [] and len(six_hours["readings"]) == 1
    assert one_hour["latest"] is not None
    assert one_hour["node"]["freshness"]["is_stale"] is True  # 7200 giây > 3900


async def test_week_range_returns_hourly_means_with_gaps(client, db, clock):
    """7 ngày: trung bình từng giờ (nhãn h = cửa sổ (h−1, h]); giờ trống vẫn có điểm null; bỏ số đo cách ly."""
    add_gateway(db)
    node_id = add_node(db, 1)
    clock.advance(minutes=10)  # 07:10 → giờ 08:00
    await ingest(client, items=[item(msg_id=1, pm25=40.0, pm10=50.0)])
    clock.advance(seconds=30)
    await ingest(client, items=[item(msg_id=2, pm25=60.0, pm10=70.0)])
    await ingest(client, gateway_id="GW_013", items=[item(msg_id=3, pm25=500.0, pm10=600.0)])  # Gateway lạ: cách ly
    clock.advance(hours=2)  # 09:10:30 → điểm cuối là giờ 10:00
    body = (await client.get(f"{URL}/{node_id}/readings", params={"hours": 168})).json()
    assert (body["resolution"], body["readings"], len(body["hourly"])) == ("hour", [], 168)
    assert body["hourly"][-1]["time"] == "2026-10-15T10:00:00Z"
    by_time = {p["time"]: p for p in body["hourly"]}
    hour = by_time["2026-10-15T08:00:00Z"]
    assert (hour["n_samples"], hour["pm25"], hour["pm10"]) == (2, 50.0, 60.0)
    assert hour["aqi"] == instant_aqi(50.0, 60.0)
    empty = by_time["2026-10-15T09:00:00Z"]
    assert (empty["n_samples"], empty["pm25"], empty["aqi"]) == (0, None, None)
    # bản ghi qua Gateway lạ có lưu (cờ UNTRUSTED_GATEWAY) nhưng không vào trung bình giờ (50 = (40 + 60) / 2)
    assert rows(db, "SELECT pm25, qc_flags FROM measurements WHERE gateway_id = 'GW_013'") == [(500.0, 256)]


async def test_month_range_and_raw_ranges_keep_shape(client, db, clock):
    add_gateway(db)
    node_id = add_node(db, 1)
    await ingest(client)
    month = (await client.get(f"{URL}/{node_id}/readings", params={"hours": 720})).json()
    day = (await client.get(f"{URL}/{node_id}/readings", params={"hours": 24})).json()
    assert (month["resolution"], len(month["hourly"])) == ("hour", 720)
    assert (day["resolution"], day["hourly"], len(day["readings"])) == ("raw", [], 1)


async def test_quarantined_reading_is_flagged(client, db, clock):
    await ingest(client, gateway_id="GW_013", items=[item(node=5)])  # Gateway lạ → pending
    [node] = (await client.get(URL)).json()
    body = (await client.get(f"{URL}/{node['id']}/readings")).json()
    assert body["readings"][0]["quarantined"] is True
    assert node["gateway"]["status"] == "pending"


async def test_bad_range_and_unknown_node(client, db):
    assert (await client.get(f"{URL}/1/readings", params={"hours": 3})).status_code == 422
    r = await client.get(f"{URL}/999/readings")
    assert r.status_code == 404 and r.json()["error"]["code"] == "NODE_NOT_FOUND"


async def test_dev_routes_absent_when_flag_off(db, monkeypatch):
    """Môi trường thật (cờ tắt): không có route /dev, trả 404."""
    off = Settings(database_url="x", provision_key="k", enable_dev_endpoints=False)
    monkeypatch.setattr(api, "get_settings", lambda: off)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.get(URL)).status_code == 404
