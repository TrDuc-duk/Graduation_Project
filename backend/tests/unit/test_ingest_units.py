"""Test thuần Python của ingest: chuẩn hóa, hash chống trùng, batch cũ, gán thời điểm đo."""

from datetime import timedelta

import pytest

from app.modules.ingest.dedup import payload_hash, rank, window_s
from app.modules.ingest.normalize import normalize
from app.modules.ingest.schemas import TelemetryItem
from app.modules.ingest.staleness import AFTER_REJECTION, GATEWAY_SILENT, check_stale, silence_threshold_s
from app.modules.ingest.timing import TimeInput, assign_times, batch_max_age_s, can_use_msg_id, msg_steps
from app.modules.telemetry.qc import QcFlag
from tests.conftest import T0
from tests.fixtures.firmware import heartbeat_item, item, sensor_error_item


def norm(**kw):
    return normalize(0, TelemetryItem(**item(**kw)))


# ---------- chuẩn hóa (6.4) ----------


def test_normal_reading_keeps_values_and_computes_aqi():
    r = norm()
    assert (r.addr, r.pm25, r.pm10, r.co2, r.tvoc, r.battery_pct, r.msg_id) == (1, 70.0, 80.5, 800, 120, 92, 12)
    assert r.flags == 0 and not r.is_heartbeat
    assert r.aqi_instant == 158  # PM2.5 70 µg/m³ theo thang AQI của ml/ml_xgb/src/aqi.py
    assert r.sensor_health == {"pms7003": "ok", "aht10": "ok", "ccs811": "ok"}


def test_all_zero_is_node_heartbeat():
    r = normalize(0, TelemetryItem(**heartbeat_item()))
    assert r.is_heartbeat and r.flags == 0 and r.sensor_health == {}


def test_sensor_errors_become_null():
    r = normalize(0, TelemetryItem(**sensor_error_item()))
    assert (r.pm25, r.pm10, r.temperature, r.humidity, r.co2, r.tvoc) == (None,) * 6
    assert r.flags == QcFlag.GAS_INVALID
    assert r.aqi_instant is None
    assert r.sensor_health == {"pms7003": "error", "aht10": "error", "ccs811": "error"}


@pytest.mark.parametrize(
    ("co2", "flag", "health"),
    [(0, QcFlag.GAS_NOT_READY, "warming_up"), (65535, QcFlag.GAS_INVALID, "error"), (300, QcFlag.GAS_INVALID, "error")],
)
def test_bad_co2_nulls_co2_and_tvoc(co2, flag, health):
    r = norm(co2=co2)
    assert r.co2 is None and r.tvoc is None and r.flags == flag
    assert r.sensor_health["ccs811"] == health


def test_out_of_range_values():
    r = norm(pm25=1500.0, temperature=99.0, humidity=120.0, tvoc=32769, battery=150)
    assert r.pm25 is None and r.temperature is None and r.humidity is None and r.tvoc is None
    assert r.battery_pct is None
    assert r.flags == QcFlag.PM_OUT_OF_RANGE | QcFlag.TH_OUT_OF_RANGE | QcFlag.GAS_INVALID


@pytest.mark.parametrize(("co2", "tvoc"), [(2359, 1477), (29206, 32768), (400, 0)])
def test_ccs811_full_output_range_is_retained(co2, tvoc):
    r = norm(co2=co2, tvoc=tvoc)
    assert (r.co2, r.tvoc, r.flags) == (co2, tvoc, 0)
    assert r.sensor_health["ccs811"] == "ok"


@pytest.mark.parametrize(("co2", "tvoc"), [(29207, 100), (800, 32769), (65535, 65535)])
def test_ccs811_outside_output_range_is_invalid(co2, tvoc):
    r = norm(co2=co2, tvoc=tvoc)
    assert r.flags & QcFlag.GAS_INVALID
    assert r.tvoc is None


def test_pm10_lt_pm25_and_high_humidity_are_marked_but_kept():
    r = norm(pm25=50.0, pm10=40.0, humidity=97.0)
    assert (r.pm25, r.pm10, r.humidity) == (50.0, 40.0, 97.0)
    assert r.flags == QcFlag.PM10_LT_PM25 | QcFlag.HIGH_HUMIDITY


def test_bad_node_id_and_msg_id():
    r = norm(node_id="SENSOR_1", msg_id=300)
    assert r.addr is None and r.msg_id is None


# ---------- chống trùng (6.5) ----------


def test_hash_is_stable_for_70_and_70_0():
    a = TelemetryItem(**item(pm25=70, co2=800))
    b = TelemetryItem(**item(pm25=70.0, co2=800.0))
    assert payload_hash(a) == payload_hash(b)


def test_hash_differs_by_value_node_and_msg_id():
    base = payload_hash(TelemetryItem(**item()))
    assert payload_hash(TelemetryItem(**item(pm25=70.1))) != base
    assert payload_hash(TelemetryItem(**item(node=2))) != base
    assert payload_hash(TelemetryItem(**item(msg_id=13))) != base
    assert payload_hash(TelemetryItem(**item(msg_id=None))) != base
    assert -(2**63) <= base < 2**63


def test_window():
    assert window_s(True, None) == 3600
    assert window_s(False, None) == 60
    assert window_s(False, 15) == 60
    assert window_s(False, 300) == 150
    assert window_s(False, 3600) == 900


def test_rank_order():
    trusted = rank(0)
    assert trusted > rank(QcFlag.TIME_UNRELIABLE) > rank(QcFlag.UNTRUSTED_GATEWAY)
    assert rank(QcFlag.UNTRUSTED_GATEWAY) > rank(QcFlag.UNTRUSTED_GATEWAY | QcFlag.TIME_UNRELIABLE)


# ---------- batch nghi cũ (6.6.3) ----------

STALE_KW = {"heartbeat_s": 300, "flush_s": 30, "factor": 2, "tolerance_s": 45}


def test_silence_threshold_examples():
    assert silence_threshold_s(15, **STALE_KW) == 105
    assert silence_threshold_s(1800, **STALE_KW) == 645
    assert silence_threshold_s(None, **STALE_KW) == 645


def test_gateway_silent_just_above_and_below_threshold():
    assert check_stale(T0, T0 - timedelta(seconds=105), None, 15, **STALE_KW) is None
    assert check_stale(T0, T0 - timedelta(seconds=106), None, 15, **STALE_KW) == GATEWAY_SILENT


def test_after_rejection_and_first_contact():
    assert check_stale(T0, T0, T0 - timedelta(minutes=1), 15, **STALE_KW) == AFTER_REJECTION
    assert check_stale(T0, None, None, 15, **STALE_KW) is None


# ---------- thời điểm đo (6.6.2, 6.6.4) ----------


def ti(*msg_ids, hb_at=None):
    return [TimeInput(m, i == hb_at) for i, m in enumerate(msg_ids)]


TIME_KW = {"prev_last_telemetry_at": T0 - timedelta(seconds=30), "stale": False, "max_msg_gap": 20, "max_age_s": 105}


def test_msg_steps_wrap():
    assert msg_steps([250, 255, 3]) == [5, 4]
    assert sum(msg_steps([250, 3])) == 9


def test_single_record_gets_receive_time():
    [r] = assign_times(ti(5), T0, 15, **TIME_KW)
    assert (r.measured_at, r.time_source, r.flags) == (T0, "received", 0)


def test_unknown_interval_keeps_receive_time_for_all():
    rs = assign_times(ti(1, 2), T0, None, **TIME_KW)
    assert all(r.measured_at == T0 and r.flags == QcFlag.INTERVAL_UNKNOWN for r in rs)


def test_msg_id_backoff_with_wrap():
    """Dãy 254 → 255 → 1 với chu kỳ 10 giây: bước 1, 2 → lùi 30 và 20 giây."""
    rs = assign_times(ti(254, 255, 1), T0, 10, **TIME_KW)
    assert [T0 - r.measured_at for r in rs] == [timedelta(seconds=30), timedelta(seconds=20), timedelta(0)]
    assert rs[0].flags == QcFlag.TIME_ESTIMATED | QcFlag.TIME_FROM_MSG_ID
    assert (rs[-1].time_source, rs[-1].flags) == ("received", 0)


def test_falls_back_to_position_when_msg_id_unusable():
    """Bước 25 > max_msg_gap → không dùng msg_id, lùi theo vị trí."""
    rs = assign_times(ti(1, 26), T0, 10, **TIME_KW)
    assert T0 - rs[0].measured_at == timedelta(seconds=10)
    assert rs[0].flags == QcFlag.TIME_ESTIMATED


def test_estimate_is_clamped_by_max_age():
    rs = assign_times(ti(None, None, None), T0, 100, **{**TIME_KW, "max_age_s": 105})
    assert T0 - rs[0].measured_at == timedelta(seconds=105)  # lẽ ra 200 giây


def test_stale_batch_marks_unreliable():
    rs = assign_times(ti(1, 2), T0, 10, **{**TIME_KW, "stale": True})
    assert all((r.measured_at, r.time_source, r.flags) == (T0, "unreliable", QcFlag.TIME_UNRELIABLE) for r in rs)


@pytest.mark.parametrize(
    ("records", "interval", "prev_gap", "expected"),
    [
        (ti(1, 2, 3), 10, 30, True),
        (ti(1, None), 10, 30, False),  # 1. thiếu msg_id
        (ti(1, 2), 600, 30, False),  # 2. chu kỳ ≥ 600 giây
        (ti(1, 2, hb_at=1), 10, 30, False),  # 3. có heartbeat trong dãy
        (ti(1, 1), 10, 30, False),  # 4. bước 0 (gói lặp)
        (ti(1, 22), 10, 300, False),  # 4. bước 21 > 20
        (ti(1, 3), 100, 30, False),  # 6. span × c = 200 > 30 + 100
    ],
)
def test_msg_id_conditions(records, interval, prev_gap, expected):
    prev = T0 - timedelta(seconds=prev_gap)
    assert can_use_msg_id(records, interval, T0, prev, False, 20) is expected


def test_batch_max_age():
    kw = {"flush_s": 30, "tolerance_s": 45}
    assert batch_max_age_s(T0, False, T0 - timedelta(seconds=30), None, **kw) == 105
    assert batch_max_age_s(T0, True, T0, T0 - timedelta(seconds=600), **kw) == 645
    assert batch_max_age_s(T0, False, None, None, **kw) is None
