"""API công khai /api/v1/public/* phần B4a (backend_design 11.3, 18 "PostGIS", "Ngôn ngữ", "Bảo mật")."""

import math
from datetime import timedelta

import pytest

from app.core import settings_store
from app.modules.hourly import service as hourly
from app.modules.telemetry.qc import QcFlag
from tests.conftest import T0
from tests.integration.helpers import add_gateway, add_node, execute
from tests.integration.test_hourly_compute import add_measurement

API = "/api/v1/public"
HN = (21.0050, 105.8430)  # Bách Khoa
HD = (21.0285, 105.8048)  # cách khoảng 4,7 km
SENSITIVE_KEYS = {"battery", "battery_pct", "gateway_id", "gateway", "remote_ip", "ip", "payload", "last_ip"}


def station(db, addr: int, coords: tuple[float, float] | None, name: str | None = None, **cols) -> int:
    """Node active, công khai, chu kỳ 900 giây; tọa độ (lat, lng) hoặc chưa có."""
    node_id = add_node(db, addr, expected_interval_s=900, interval_locked=True, name=name or f"Trạm {addr}", **cols)
    if coords:
        execute(db, "UPDATE nodes SET geom = ST_SetSRID(ST_MakePoint(:lng, :lat), 4326) WHERE id = :id",
                lat=coords[0], lng=coords[1], id=node_id)  # fmt: skip
    return node_id


@pytest.fixture
def two_stations(db, clock):
    """ST001 có số đo và giờ 14:00 đã đóng (AQI ~ 158); ST002 có tọa độ nhưng chưa có dữ liệu. Giờ: 14:05."""
    add_gateway(db)
    a = station(db, 1, HN, district="Hai Bà Trưng")
    station(db, 2, HD)
    add_measurement(db, a, T0 - timedelta(minutes=40), pm25=70.04, pm10=80.0, temperature=32.46, humidity=70.0)
    add_measurement(db, a, T0 - timedelta(minutes=5), pm25=70.06, pm10=80.0, temperature=32.5, humidity=71.0,
                    co2=800, tvoc=120)  # fmt: skip
    clock.at = T0 + timedelta(minutes=5)
    return a


def walk_keys(obj) -> set[str]:
    """Mọi tên khóa trong JSON lồng nhau."""
    if isinstance(obj, dict):
        return set(obj) | set().union(*(walk_keys(v) for v in obj.values()))
    if isinstance(obj, list):
        return set().union(*(walk_keys(v) for v in obj)) if obj else set()
    return set()


async def test_empty_system(client, db):
    assert (await client.get(f"{API}/stations")).json() == {"items": []}
    assert (await client.get(f"{API}/stations.geojson")).json() == {"type": "FeatureCollection", "features": []}
    o = (await client.get(f"{API}/overview")).json()
    assert (o["n_stations"], o["aqi_avg"], o["most_polluted"], o["default_station_id"]) == (0, None, None, None)


async def test_station_list_fields_and_hourly(client, db, two_stations):
    await hourly.close_hour(T0, T0 + timedelta(minutes=3))
    r = await client.get(f"{API}/stations")
    assert r.status_code == 200
    a, b = r.json()["items"]
    assert (a["id"], a["name"], a["district"], a["environment"], a["is_simulated"], a["online"]) == (
        "ST001", "Trạm 1", "Hai Bà Trưng", "outdoor", False, True,
    )  # fmt: skip
    assert (a["latitude"], a["longitude"]) == HN
    latest = a["latest"]
    assert latest["measured_at"] == "2026-10-15T13:55:00+07:00"
    assert (latest["pm25"], latest["temperature"], latest["age_minutes"], latest["co2"]) == (70.1, 32.5, 10, 800)
    h = a["hourly"]
    assert (h["hour_end"], h["n_samples"], h["coverage"], h["dominant"]) == (
        "2026-10-15T14:00:00+07:00",
        2,
        0.5,
        "pm25",
    )
    assert h["aqi"] == 158 and h["level"] == "unhealthy"
    assert (b["id"], b["latest"], b["hourly"], b["online"]) == ("ST002", None, None, False)
    assert not walk_keys(r.json()) & SENSITIVE_KEYS


async def test_only_active_public_stations_with_coordinates(client, db, clock):
    """Trạm chưa có tọa độ, chờ duyệt, ẩn công khai, ngưng hoạt động không xuất hiện; chi tiết trả 404."""
    station(db, 1, HN)
    station(db, 2, None)  # chưa có tọa độ
    station(db, 3, HN, status="pending")
    station(db, 4, HN, is_public=False)
    assert [s["id"] for s in (await client.get(f"{API}/stations")).json()["items"]] == ["ST001"]
    for code in ("ST002", "ST003", "ST004", "ST999"):
        r = await client.get(f"{API}/stations/{code}")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "STATION_NOT_FOUND"


async def test_detail_lowercase_code_freshness_units(client, db, two_stations):
    r = await client.get(f"{API}/stations/st001")
    assert r.status_code == 200
    d = r.json()
    assert d["id"] == "ST001"
    assert d["freshness"] == {"last_received_at": "2026-10-15T13:55:00+07:00", "age_s": 600, "stale_after_s": 3900,
                              "is_stale": False}  # fmt: skip
    assert d["units"]["pm25"] == "µg/m³" and d["units"]["tvoc"] == "ppb"
    assert d["hourly"] is None  # giờ 14:00 chưa đóng


async def test_latest_skips_excluded_and_stale_station_goes_offline(client, db, two_stations, clock):
    """Số đo nghi cũ không là số đo hiện tại; quá ngưỡng 3900 giây không có số đo mới → online = false."""
    add_measurement(db, two_stations, T0 + timedelta(minutes=1), flags=QcFlag.TIME_UNRELIABLE, pm25=999.0, pm10=999.0)
    d = (await client.get(f"{API}/stations/ST001")).json()
    assert d["latest"]["pm25"] == 70.1
    clock.at = T0 + timedelta(hours=2)
    d = (await client.get(f"{API}/stations/ST001")).json()
    assert (d["online"], d["freshness"]["is_stale"]) == (False, True)


async def test_hourly_older_than_two_hours_is_not_current(client, db, two_stations, clock):
    """AQI giờ hiện hành không quá 2 giờ; cũ hơn thì không hiện màu/cảnh báo theo mức (11.3)."""
    await hourly.close_hour(T0, T0 + timedelta(minutes=3))
    clock.at = T0 + timedelta(hours=1, minutes=59)
    assert (await client.get(f"{API}/stations/ST001")).json()["hourly"] is not None
    clock.at = T0 + timedelta(hours=2)
    assert (await client.get(f"{API}/stations/ST001")).json()["hourly"] is None


def haversine_m(p: tuple[float, float], q: tuple[float, float]) -> float:
    """Khoảng cách tính tay trên mặt cầu bán kính 6 371 008,8 m."""
    (la1, lo1), (la2, lo2) = (map(math.radians, p), map(math.radians, q))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6_371_008.8 * math.asin(math.sqrt(h))


async def test_nearest_order_and_distance(client, db, two_stations):
    """Xếp theo khoảng cách geography; khoảng cách khớp giá trị tính tay (lệch < 0,5 % do mô hình elipsoid)."""
    me = (21.0270, 105.8100)  # gần ST002 hơn
    r = await client.get(f"{API}/stations/nearest", params={"lat": me[0], "lng": me[1], "limit": 2})
    assert r.status_code == 200
    items = r.json()["items"]
    assert [i["id"] for i in items] == ["ST002", "ST001"]
    for item, coords in zip(items, (HD, HN), strict=True):
        assert abs(item["distance_m"] - haversine_m(me, coords)) / haversine_m(me, coords) < 0.005
    assert len((await client.get(f"{API}/stations/nearest", params={"lat": 21, "lng": 105})).json()["items"]) == 2


@pytest.mark.parametrize("params", [{"lat": 100, "lng": 105}, {"lat": 21}, {"lat": 21, "lng": 105, "limit": 0}])
async def test_nearest_rejects_bad_params(client, db, params):
    r = await client.get(f"{API}/stations/nearest", params=params)
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_PARAMS"


async def test_geojson(client, db, two_stations):
    fc = (await client.get(f"{API}/stations.geojson")).json()
    first = fc["features"][0]
    assert (first["type"], first["id"], first["geometry"]["type"]) == ("Feature", "ST001", "Point")
    assert first["geometry"]["coordinates"] == [HN[1], HN[0]]  # GeoJSON: [lng, lat]
    assert "latitude" not in first["properties"] and first["properties"]["name"] == "Trạm 1"


async def test_overview_counts_and_default_station(client, db, two_stations):
    await hourly.close_hour(T0, T0 + timedelta(minutes=3))
    execute(db, "INSERT INTO app_settings (key, value) VALUES ('default_station_id', '\"st001\"')")
    settings_store.clear_cache()
    o = (await client.get(f"{API}/overview")).json()
    assert (o["n_stations"], o["n_online"], o["aqi_avg"], o["default_station_id"]) == (2, 1, 158, "ST001")
    assert o["most_polluted"] == {"id": "ST001", "name": "Trạm 1", "aqi": 158, "level": "unhealthy"}
    assert o["last_updated_at"] == "2026-10-15T13:55:00+07:00"


async def test_default_station_hidden_when_not_public(client, db, clock):
    """Trạm mặc định chưa có tọa độ thì trang chủ không dùng được: trả null để giao diện cho chọn trạm."""
    station(db, 1, None)
    execute(db, "INSERT INTO app_settings (key, value) VALUES ('default_station_id', '\"ST001\"')")
    settings_store.clear_cache()
    assert (await client.get(f"{API}/overview")).json()["default_station_id"] is None


async def test_language_headers_and_messages(client, db):
    """Accept-Language đổi nhãn, không đổi mã; ?lang= ghi đè; có Content-Language và Vary."""
    vi = await client.get(f"{API}/aqi-scale")
    en = await client.get(f"{API}/aqi-scale", headers={"Accept-Language": "en-US,en;q=0.9"})
    assert (vi.headers["content-language"], en.headers["content-language"]) == ("vi", "en")
    assert en.headers["vary"] == "Accept-Language"
    assert [x["level"] for x in vi.json()["items"]] == [x["level"] for x in en.json()["items"]]
    assert en.json()["items"][0]["label"] == "Good" and vi.json()["items"][0]["label"] == "Tốt"
    assert (await client.get(f"{API}/aqi-scale?lang=en", headers={"Accept-Language": "vi"})).json()["items"][0][
        "label"
    ] == "Good"
    r = await client.get(f"{API}/stations/ST404", headers={"Accept-Language": "en"})
    assert r.json()["error"]["message"] == "Station ST404 was not found."


async def test_simulated_flag_is_public(client, db, clock):
    station(db, 1, HN, is_simulated=True)
    assert (await client.get(f"{API}/stations/ST001")).json()["is_simulated"] is True
