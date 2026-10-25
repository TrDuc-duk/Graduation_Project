"""API trợ lý /api/v1/assistant/*: xác thực, nhận diện trạm, số liệu khớp backend, dữ liệu thiếu/cũ, nhật ký."""

from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from app import api
from app.core.config import Settings
from app.core.db import run_in_transaction
from app.main import create_app
from app.modules.assistant import service
from app.modules.stations import service as stations
from tests.fixtures.firmware import item, sensor_error_item, telemetry
from tests.integration.helpers import add_gateway, add_node, execute, rows

URL = "/api/v1/assistant"
AUTH = {"Authorization": "Bearer test-assistant-token"}
ADMIN_FIELDS = {"battery_pct", "gateway", "gateway_id", "qc_flags", "device_code", "status"}


async def get(client, path: str, **params):
    """Gọi API trợ lý bằng token đúng."""
    return await client.get(f"{URL}{path}", params=params, headers=AUTH)


async def ingest(client, gateway_id: str = "GW_001", items: list | None = None) -> None:
    r = await client.post("/api/v1/telemetry", json=telemetry(gateway_id=gateway_id, items=items or [item()]))
    assert r.status_code == 200


def set_default(db, code: str) -> None:
    execute(
        db, "INSERT INTO app_settings (key, value) VALUES ('default_station_id', to_jsonb(CAST(:c AS text)))", c=code
    )


def all_keys(value) -> set[str]:
    """Mọi khóa trong JSON lồng nhau (để kiểm tra không lộ trường quản trị)."""
    if isinstance(value, dict):
        return set(value) | {k for v in value.values() for k in all_keys(v)}
    if isinstance(value, list):
        return {k for v in value for k in all_keys(v)}
    return set()


async def test_token_required(client, db):
    r = await client.get(f"{URL}/stations")
    assert r.status_code == 401 and r.json() == {
        "ok": False,
        "code": "UNAUTHORIZED",
        "message_vi": "Thiếu hoặc sai token trợ lý.",
    }
    r = await client.get(f"{URL}/stations", headers={"Authorization": "Bearer sai"})
    assert r.status_code == 401
    assert (await get(client, "/stations")).status_code == 200


async def test_routes_absent_without_token(db, monkeypatch):
    """ASSISTANT_TOKEN trống: không mở API trợ lý."""
    off = Settings(database_url="x", provision_key="k", assistant_token="")
    monkeypatch.setattr(api, "get_settings", lambda: off)
    async with AsyncClient(transport=ASGITransport(app=create_app()), base_url="http://test") as c:
        assert (await c.get(f"{URL}/stations", headers=AUTH)).status_code == 404


async def test_list_hides_pending_and_reports_default(client, db):
    add_node(db, 1, name="Bách Khoa", district="Hai Bà Trưng")
    add_node(db, 2, status="pending", name="Chờ duyệt")
    set_default(db, "ST001")
    body = (await get(client, "/stations")).json()
    assert [s["code"] for s in body["stations"]] == ["ST001"]
    assert body["stations"][0] == {
        "code": "ST001",
        "name": "Bách Khoa",
        "district": "Hai Bà Trưng",
        "online": False,
        "last_measured_at": None,
    }
    assert body["default_station"] == "ST001" and "Trạm mặc định là ST001" in body["summary_vi"]


async def test_current_matches_stored_reading(client, db, clock):
    add_gateway(db)
    node_id = add_node(db, 1, name="Bách Khoa")
    await ingest(client, items=[item(pm25=43.0, pm10=51.0, temperature=33.9, humidity=70.8)])
    clock.advance(minutes=5)
    r = await get(client, "/stations/st001/current")
    body = r.json()
    assert r.status_code == 200 and body["ok"] is True
    # Chưa có giờ nào đóng: AQI giờ null, không thay bằng AQI tức thời (aqi_instant riêng)
    assert (body["aqi_kind"], body["aqi"], body["hourly_aqi"], body["level"]) == ("hourly", None, None, None)
    assert (body["aqi_instant"], body["aqi_hour_end"]) == (119, None)
    assert (body["pm25"], body["pm10"], body["temperature"], body["humidity"]) == (43.0, 51.0, 33.9, 70.8)
    assert body["measured_at"] == "2026-10-15T14:00:00+07:00" and body["age_minutes"] == 5
    assert body["stale"] is False and body["units"]["pm25"] == "µg/m³"
    assert "chưa có AQI giờ" in body["summary_vi"] and "AQI tức thời 119" in body["summary_vi"]
    assert "14:00 ngày 15/10" in body["summary_vi"]
    assert not all_keys(body) & ADMIN_FIELDS
    # cùng số đo với API dev của web
    [dev] = (await client.get("/api/v1/dev/nodes")).json()
    assert (dev["latest"]["aqi_instant"], dev["latest"]["pm25"]) == (body["aqi_instant"], body["pm25"])
    [log] = rows(db, "SELECT tool, params, station_code, node_id, status, error_code FROM assistant_calls")
    assert log == ("get_current_air_quality", {"station": "st001"}, "ST001", node_id, "ok", None)


async def test_current_stale_and_null_values(client, db, clock):
    add_gateway(db)
    add_node(db, 1, name="Bách Khoa")
    await ingest(client, items=[sensor_error_item()])
    clock.advance(hours=2)  # quá 3900 giây không có số đo mới
    body = (await get(client, "/stations/default/current")).json()
    assert body["code"] == "DEFAULT_STATION_NOT_SET" and [s["code"] for s in body["stations"]] == ["ST001"]
    body = (await get(client, "/stations/Bách Khoa/current")).json()
    assert (body["pm25"], body["aqi"], body["level"], body["stale"]) == (None, None, None, True)
    assert body["summary_vi"].startswith("Lưu ý: dữ liệu của trạm đã cũ, lần cập nhật cuối lúc 14:00 ngày 15/10.")
    assert "PM2.5 không có số đo" in body["summary_vi"] and "chưa tính được AQI tức thời" in body["summary_vi"]


async def test_station_errors(client, db):
    add_node(db, 1, name="Bách Khoa")
    add_node(db, 2, name="Bách Khoa 2")
    r = await get(client, "/stations/Cầu Giấy/current")
    assert r.status_code == 404 and r.json()["code"] == "STATION_NOT_FOUND"
    assert [s["code"] for s in r.json()["stations"]] == ["ST001", "ST002"]
    r = await get(client, "/stations/bach/current")
    assert r.status_code == 409 and [c["code"] for c in r.json()["candidates"]] == ["ST001", "ST002"]
    r = await get(client, "/stations/ST001/current")
    assert r.status_code == 404 and r.json()["code"] == "NO_DATA"
    codes = rows(db, "SELECT error_code FROM assistant_calls ORDER BY id")
    assert [c for (c,) in codes] == ["STATION_NOT_FOUND", "STATION_AMBIGUOUS", "NO_DATA"]


async def test_summary_matches_stations_service(client, db, clock):
    add_gateway(db)
    node_id = add_node(db, 1, name="Bách Khoa")
    for i, pm in enumerate([20.0, 22.0, 30.0, 45.0, 50.0, 55.0]):
        await ingest(client, items=[item(msg_id=i, pm25=pm, pm10=pm + 10)])
        clock.advance(minutes=10)
    body = (await get(client, "/stations/ST001/summary", hours="6")).json()
    expected = await run_in_transaction(lambda s: stations.summary(s, node_id, 6, clock.now()))
    assert body["n_samples"] == expected.n_samples == 6
    assert body["metrics"]["pm25"] == {
        "avg": expected.metrics["pm25"].avg,
        "min": 20.0,
        "max": 55.0,
        "n": 6,
        "trend": "increasing",
        "trend_label": "tăng",
    }
    assert (body["data_from"], body["data_to"]) == ("2026-10-15T14:00:00+07:00", "2026-10-15T14:50:00+07:00")
    assert "xu hướng tăng" in body["summary_vi"]


async def test_summary_params_and_empty_window(client, db, clock):
    add_gateway(db)
    add_node(db, 1, name="Bách Khoa")
    await ingest(client)
    for bad in ("0", "73", "abc"):
        r = await get(client, "/stations/ST001/summary", hours=bad)
        assert r.status_code == 422 and r.json()["code"] == "INVALID_PARAMS"
    clock.advance(hours=30)
    r = await get(client, "/stations/ST001/summary")  # mặc định 24 giờ
    assert r.status_code == 404 and r.json()["code"] == "NO_DATA"
    assert r.json()["last_measured_at"] == "2026-10-15T14:00:00+07:00"


async def test_forecast_unavailable_without_numbers(client, db):
    add_node(db, 1, name="Bách Khoa")
    set_default(db, "ST001")
    body = (await get(client, "/stations/default/forecast")).json()
    assert (body["status"], body["forecast"], body["horizons"]) == ("unavailable", None, [3, 6, 12, 24])
    assert (await get(client, "/stations/ST001/forecast", horizons="6,3,6")).json()["horizons"] == [3, 6]
    r = await get(client, "/stations/ST001/forecast", horizons="4")
    assert r.status_code == 422 and r.json()["code"] == "INVALID_PARAMS"


async def test_database_error_becomes_backend_unavailable(client, db, monkeypatch):
    async def broken(*_):
        raise OperationalError("SELECT 1", {}, Exception("mất kết nối"))

    monkeypatch.setattr(service, "list_stations", broken)
    r = await get(client, "/stations")
    assert r.status_code == 503 and r.json()["code"] == "BACKEND_UNAVAILABLE"


async def test_current_hourly_aqi_matches_public_api(client, db, clock):
    """Cùng trạm, cùng thời điểm: AQI giờ của trợ lý trùng `hourly.aqi` của /public; mức theo AQI giờ (B7)."""
    from datetime import timedelta

    from app.modules.hourly import service as hourly

    add_gateway(db)
    node_id = add_node(db, 1, name="Bách Khoa", expected_interval_s=900, interval_locked=True)
    execute(db, "UPDATE nodes SET geom = ST_SetSRID(ST_MakePoint(105.843, 21.005), 4326) WHERE id = :id", id=node_id)
    clock.advance(seconds=-20)  # 13:59:40: số đo thuộc giờ 14:00
    await ingest(client, items=[item(pm25=43.0, pm10=51.0)])
    clock.advance(seconds=30)  # 14:00:10: Gateway xả buffer tiếp theo (30 giây), giờ 15:00 đang mở
    await hourly.close_hour(clock.at - timedelta(seconds=10), clock.at + timedelta(minutes=3))
    await ingest(client, items=[item(msg_id=13, pm25=80.0, pm10=90.0)])

    body = (await get(client, "/stations/ST001/current")).json()
    public = (await client.get("/api/v1/public/stations/ST001")).json()
    assert body["aqi"] == body["hourly_aqi"] == public["hourly"]["aqi"] == 119
    assert (body["aqi_kind"], body["level"], body["aqi_hour_end"]) == ("hourly", "usg", "2026-10-15T14:00:00+07:00")
    assert body["aqi_instant"] == public["latest"]["aqi_instant"] and body["pm25"] == 80.0
    assert body["measured_at"] == "2026-10-15T14:00:10+07:00"
    assert "AQI giờ 119" in body["summary_vi"] and "từ 13:00 đến 14:00" in body["summary_vi"]
