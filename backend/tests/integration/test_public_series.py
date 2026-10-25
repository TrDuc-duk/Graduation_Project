"""API công khai B4b: chuỗi thời gian, chu kỳ ngày, xếp hạng, giới hạn tần suất (backend_design 11.3–11.4, 14.2)."""

from datetime import timedelta

import pytest
from src.aqi import compute_aqi

from app.modules.hourly import service as hourly
from app.modules.telemetry.qc import QcFlag
from tests.conftest import T0
from tests.integration.helpers import add_gateway, rows, scalar
from tests.integration.test_hourly_compute import add_measurement
from tests.integration.test_public_api import HD, HN, station

API = "/api/v1/public"
H = timedelta(hours=1)


@pytest.fixture
def st(db, clock):
    """ST001 (công khai, có tọa độ) với số đo ở giờ 13:00 và 15:00 (giờ 14:00 trống). Giờ hiện tại 15:10."""
    add_gateway(db)
    node = station(db, 1, HN)
    add_measurement(db, node, T0 - H - timedelta(minutes=30), pm25=12.0, pm10=20.0, temperature=30.0)
    add_measurement(db, node, T0 - H - timedelta(minutes=20), pm25=12.2, pm10=20.0, temperature=30.2, co2=801)
    add_measurement(db, node, T0 + H - timedelta(minutes=10), pm25=39.9, pm10=50.0)
    add_measurement(db, node, T0 + H - timedelta(minutes=8), flags=QcFlag.TIME_UNRELIABLE, pm25=500.0, pm10=500.0)
    clock.at = T0 + H + timedelta(minutes=10)
    return node


async def close_all():
    for h in (T0 - H, T0, T0 + H):
        await hourly.close_hour(h, h + timedelta(minutes=3))


async def test_hour_series_columns_and_gaps(client, db, st):
    """Lưới giờ đủ mọi nhãn trong (from, to]; giờ trống → null, n_samples 0; giữ đúng dạng cột của §11.4."""
    await close_all()
    params = {"resolution": "hour", "from": "2026-10-15T12:00:00+07:00", "to": "2026-10-15T15:00:00+07:00",
              "metrics": "aqi,pm25,temperature,co2"}  # fmt: skip
    r = await client.get(f"{API}/stations/ST001/series", params=params)
    assert r.status_code == 200
    s = r.json()
    assert set(s) == {"station_id", "resolution", "from", "to", "time", "aqi", "pm25", "temperature", "co2",
                      "n_samples", "coverage", "units"}  # fmt: skip
    assert s["time"] == ["2026-10-15T13:00:00+07:00", "2026-10-15T14:00:00+07:00", "2026-10-15T15:00:00+07:00"]
    assert s["aqi"] == [51, None, int(compute_aqi(39.9, 50.0))]  # 12,0 và 12,2 → 12,1 → 51
    assert s["pm25"] == [12.1, None, 39.9] and s["temperature"] == [30.1, None, None] and s["co2"] == [801, None, None]
    assert s["n_samples"] == [2, 0, 1] and s["coverage"] == [0.5, None, 0.25]
    assert s["units"] == {"pm25": "µg/m³", "temperature": "°C", "co2": "ppm"}
    assert (s["station_id"], s["resolution"], s["from"]) == ("ST001", "hour", "2026-10-15T12:00:00+07:00")


async def test_default_series_is_24_hours_by_hour(client, db, st):
    s = (await client.get(f"{API}/stations/ST001/series")).json()
    assert s["resolution"] == "hour" and len(s["time"]) == 24
    assert set(s) >= {"aqi", "pm25", "pm10", "temperature", "humidity"} and "co2" not in s


async def test_raw_series_skips_excluded_samples(client, db, st):
    """Số đo thô công khai bỏ bản nghi cũ/cách ly; AQI là AQI tức thời của từng mẫu."""
    params = {"resolution": "raw", "from": "2026-10-15T12:00:00+07:00", "metrics": "aqi,pm25"}
    s = (await client.get(f"{API}/stations/ST001/series", params=params)).json()
    assert s["pm25"] == [12.0, 12.2, 39.9]
    assert s["time"][0] == "2026-10-15T12:30:00+07:00"
    assert s["aqi"] == [None, None, None]  # add_measurement không đặt aqi_instant (ingest mới tính)


async def test_5min_series_labels_end_of_bucket(client, db, st):
    """Khung 5 phút (t − 5', t] mang nhãn t; AQI = compute_aqi của PM trung bình khung."""
    params = {"resolution": "5min", "from": "2026-10-15T12:25:00+07:00", "to": "2026-10-15T12:45:00+07:00",
              "metrics": "aqi,pm25"}  # fmt: skip
    s = (await client.get(f"{API}/stations/ST001/series", params=params)).json()
    assert s["time"] == [f"2026-10-15T12:{m}:00+07:00" for m in ("30", "35", "40", "45")]
    assert s["pm25"] == [12.0, None, 12.2, None]
    assert s["aqi"][0] == int(compute_aqi(12.0, 20.0))


async def test_day_series(client, db, st):
    await close_all()
    params = {"resolution": "day", "from": "2026-10-14T00:00:00+07:00", "to": "2026-10-16T00:00:00+07:00",
              "metrics": "aqi,pm25"}  # fmt: skip
    s = (await client.get(f"{API}/stations/ST001/series", params=params)).json()
    assert s["time"] == ["2026-10-14", "2026-10-15"]
    assert s["pm25"] == [None, 26.0] and s["n_hours"] == [0, 2]


@pytest.mark.parametrize(
    ("resolution", "days", "max_days"), [("raw", 3, 2), ("5min", 8, 7), ("hour", 91, 90), ("day", 731, 730)]
)
async def test_range_too_large(client, db, st, resolution, days, max_days):
    to = T0 + H
    params = {"resolution": resolution, "from": (to - timedelta(days=days)).isoformat(), "to": to.isoformat()}
    r = await client.get(f"{API}/stations/ST001/series", params=params)
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "RANGE_TOO_LARGE" and err["details"] == {"resolution": resolution, "max_days": max_days}


@pytest.mark.parametrize(
    "params",
    [{"metrics": "aqi,battery"}, {"metrics": ""}, {"resolution": "1min"},
     {"from": "2026-10-15T15:00:00+07:00", "to": "2026-10-15T14:00:00+07:00"}],
)  # fmt: skip
async def test_series_bad_params(client, db, st, params):
    r = await client.get(f"{API}/stations/ST001/series", params=params)
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_PARAMS"


async def test_series_naive_time_is_vietnam_time(client, db, st):
    params = {"from": "2026-10-15T12:00:00", "to": "2026-10-15T13:00:00"}
    s = (await client.get(f"{API}/stations/ST001/series", params=params)).json()
    assert s["time"] == ["2026-10-15T13:00:00+07:00"]


async def test_series_and_profile_unknown_station(client, db, st):
    station(db, 2, None)  # chưa có tọa độ → không công khai
    for path in ("ST002/series", "ST999/series", "ST002/profile"):
        assert (await client.get(f"{API}/stations/{path}")).status_code == 404


async def test_profile_24_hours(client, db, st):
    await close_all()
    p = (await client.get(f"{API}/stations/ST001/profile", params={"days": 7})).json()
    assert (p["station_id"], p["days"], len(p["items"])) == ("ST001", 7, 24)
    by_hour = {i["hour_of_day"]: i for i in p["items"]}
    assert by_hour[13] == {"hour_of_day": 13, "aqi": 51, "n_hours": 1}
    assert by_hour[14] == {"hour_of_day": 14, "aqi": None, "n_hours": 0}
    assert (await client.get(f"{API}/stations/ST001/profile", params={"days": 91})).status_code == 422


async def test_ranking_offline_last(client, db, st, clock):
    """Cao trước; trạm không có AQI giờ hoặc mất kết nối xếp cuối, có cờ online."""
    other = station(db, 2, HD)
    add_measurement(db, other, T0 + H - timedelta(minutes=30), pm25=150.0, pm10=100.0)
    station(db, 3, HD)  # chưa có dữ liệu
    await close_all()
    r = (await client.get(f"{API}/ranking")).json()
    assert r["metric"] == "aqi"
    assert [(i["rank"], i["id"], i["online"]) for i in r["items"]] == [(1, "ST002", True), (2, "ST001", True),
                                                                        (3, "ST003", False)]  # fmt: skip
    assert r["items"][0]["level"] == "unhealthy" and r["items"][0]["hour_end"] == "2026-10-15T15:00:00+07:00"
    assert (await client.get(f"{API}/ranking", params={"metric": "pm25"})).json()["items"][0]["pm25"] == 150.0
    assert (await client.get(f"{API}/ranking", params={"metric": "battery"})).status_code == 422


async def test_public_rate_limit_per_ip(client, db):
    """120 request/phút mỗi IP; request thứ 121 nhận 429 RATE_LIMITED và có security_events."""
    for _ in range(120):
        assert (await client.get(f"{API}/aqi-scale")).status_code == 200
    r = await client.get(f"{API}/aqi-scale")
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"
    assert scalar(db, "SELECT count(*) FROM security_events WHERE kind = 'rate_limited'") == 1
    assert rows(db, "SELECT details->>'scope' AS scope FROM security_events")[0].scope == "public"
