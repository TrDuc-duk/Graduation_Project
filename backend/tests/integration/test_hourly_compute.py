"""Integration test tính giờ qua DB thật (backend_design 7, 18): số đo thô → tổng hợp → node_hourly → chuỗi."""

from datetime import UTC, date, datetime, timedelta

import pytest
from src.aqi import compute_aqi

from app.core.db import get_sessionmaker
from app.modules.hourly import repository, service
from app.modules.hourly.aggregate import aggregate_hour
from app.modules.telemetry.qc import QcFlag
from tests.integration.helpers import add_gateway, add_node, execute, rows

H14 = datetime(2026, 10, 15, 7, 0, tzinfo=UTC)  # 14:00 giờ Việt Nam


def add_measurement(
    engine,
    node_id: int,
    measured_at: datetime,
    *,
    received_at=None,
    trusted_at="same",
    superseded_at=None,
    flags: int = 0,
    **values,
) -> None:
    """Chèn một số đo; mặc định nhận ngay khi đo và đã tin cậy. Cờ phải khớp cột thời điểm (CHECK R21)."""
    received_at = received_at or measured_at
    if trusted_at == "same":
        trusted_at = None if flags & QcFlag.UNTRUSTED_GATEWAY else received_at
    cols = {"pm25": None, "pm10": None, "temperature": None, "humidity": None, "co2": None, "tvoc": None, **values}
    execute(
        engine,
        "INSERT INTO measurements (node_id, gateway_id, seq, time_source, payload_hash, measured_at, received_at, "
        "trusted_at, superseded_at, qc_flags, pm25, pm10, temperature, humidity, co2, tvoc) VALUES "
        "(:node, 'GW_001', 0, 'received', 1, :m, :r, :t, :s, :f, :pm25, :pm10, :temperature, :humidity, :co2, :tvoc)",
        node=node_id,
        m=measured_at,
        r=received_at,
        t=trusted_at,
        s=superseded_at,
        f=flags,
        **cols,
    )


@pytest.fixture
def node(db):
    """Node active, chu kỳ khóa 900 giây (4 mẫu/giờ), Gateway GW_001."""
    add_gateway(db)
    return add_node(db, 1, expected_interval_s=900, interval_locked=True)


async def _compute(node_id: int, first: datetime, last: datetime, cutoff=None):
    """Gọi service.compute_hours trong một session."""
    from app.modules.devices import service as devices

    async with get_sessionmaker()() as session:
        n = await devices.get_node(session, node_id)
        return await service.compute_hours(session, n, first, last, cutoff)


async def test_compute_from_db_window_flags_and_superseded(db, node):
    """Đúng cửa sổ (h−1, h]; mẫu cách ly đếm n_excluded; bản SUPERSEDED bị bỏ hẳn, không đếm."""
    add_measurement(db, node, H14 - timedelta(minutes=40), pm25=12.0, pm10=20.0, temperature=30.0)
    add_measurement(db, node, H14, pm25=12.2, pm10=30.0, temperature=31.0)  # đúng 14:00:00 → giờ 14:00
    add_measurement(db, node, H14 + timedelta(seconds=1), pm25=99.0, pm10=99.0)  # → giờ 15:00
    add_measurement(db, node, H14 - timedelta(minutes=10), flags=QcFlag.UNTRUSTED_GATEWAY, pm25=400.0, pm10=400.0)
    add_measurement(
        db, node, H14 - timedelta(minutes=5), flags=QcFlag.SUPERSEDED, superseded_at=H14, pm25=300.0, pm10=300.0
    )
    out = await _compute(node, H14, H14 + timedelta(hours=1))
    h = out[H14]
    assert (h.n_samples, h.n_excluded, h.n_pm25, h.expected_samples, h.coverage) == (2, 1, 2, 4.0, 0.5)
    assert h.aqi == 51 and h.temperature_avg == 30.5 and h.pm25_max == 12.2
    assert out[H14 + timedelta(hours=1)].n_samples == 1


async def test_upsert_roundtrip_keeps_double_precision(db, node):
    """Ghi qua repository rồi đọc lại bằng series_hour: giá trị double giữ nguyên, coverage real, revision."""
    add_measurement(db, node, H14 - timedelta(minutes=40), pm25=12.0, pm10=20.0)
    add_measurement(db, node, H14, pm25=12.2, pm10=30.0)
    agg = (await _compute(node, H14, H14))[H14]
    async with get_sessionmaker()() as session:
        await repository.upsert_hour(session, node, agg, is_closed=True, revision=0, at=H14)
        await session.commit()
        [row] = await service.series_hour(session, node, H14 - timedelta(hours=1), H14)
    assert row.pm25_avg == agg.pm25_avg and row.aqi == agg.aqi == 51
    assert (row.coverage, row.is_closed, row.revision) == (0.5, True, 0)


# Trung bình giờ đúng tại ngưỡng của bảng AQI (backend_design 18 "Ngưỡng AQI qua DB")
THRESHOLDS = [
    (12.0, 0.0),
    (12.1, 0.0),
    (35.4, 0.0),
    (35.5, 0.0),
    (55.4, 0.0),
    (55.5, 0.0),
    (150.4, 0.0),
    (150.5, 0.0),
    (250.4, 0.0),
    (250.5, 0.0),
    (0.0, 54.0),
    (0.0, 55.0),
    (0.0, 154.0),
    (0.0, 155.0),
    (0.0, 254.0),
    (0.0, 255.0),
]


async def test_aqi_thresholds_through_db(db, node):
    """Mỗi giờ hai mẫu đối xứng quanh giá trị ngưỡng; AQI giờ đọc lại từ DB bằng compute_aqi của giá trị thập phân."""
    for i, (pm25, pm10) in enumerate(THRESHOLDS):
        hour = H14 + timedelta(hours=i)
        for delta, minute in ((-0.1, 40), (0.1, 10)):
            add_measurement(db, node, hour - timedelta(minutes=minute), pm25=pm25 + delta, pm10=pm10 + delta * 10)
    last = H14 + timedelta(hours=len(THRESHOLDS) - 1)
    out = await _compute(node, H14, last)
    async with get_sessionmaker()() as session:
        for agg in out.values():
            await repository.upsert_hour(session, node, agg, is_closed=True, revision=0, at=last)
        await session.commit()
        stored = await service.series_hour(session, node, H14 - timedelta(hours=1), last)
    assert [r.aqi for r in stored] == [int(compute_aqi(pm25, pm10)) for pm25, pm10 in THRESHOLDS]


async def test_as_of_uses_state_at_cutoff(db, node):
    """R21: bản ghi nhận sau cutoff bị bỏ; Gateway duyệt sau cutoff → loại; bản sao tốt hơn đến sau cutoff →
    bản cũ vẫn dùng tại cutoff."""
    cutoff = H14 + timedelta(minutes=5)
    late_trust = H14 + timedelta(minutes=30)
    add_measurement(db, node, H14 - timedelta(minutes=50), pm25=10.0, pm10=10.0)  # bình thường
    add_measurement(db, node, H14 - timedelta(minutes=40), pm25=20.0, pm10=20.0, trusted_at=late_trust)
    add_measurement(  # bị thay lúc 14:30 → tại cutoff còn hiệu lực
        db, node, H14 - timedelta(minutes=30), pm25=30.0, pm10=30.0, flags=QcFlag.SUPERSEDED, superseded_at=late_trust
    )
    add_measurement(db, node, H14 - timedelta(minutes=20), received_at=late_trust, pm25=40.0, pm10=40.0)  # nhận muộn

    async with get_sessionmaker()() as session:
        [at_cutoff] = await service.hourly_as_of(session, node, H14, H14, cutoff)
    assert (at_cutoff.n_samples, at_cutoff.n_excluded, at_cutoff.pm25_avg) == (2, 1, 20.0)  # 10 và 30; 20 bị loại

    now = (await _compute(node, H14, H14))[H14]
    assert (now.n_samples, now.n_excluded, now.pm25_avg) == (3, 0, 70.0 / 3)  # 10, 20, 40; bản 30 đã bị thay


async def test_as_of_unknown_node_is_empty(db):
    async with get_sessionmaker()() as session:
        assert await service.hourly_as_of(session, 999, H14, H14, H14) == []


async def test_series_day_and_profile(db, node):
    """Ngày theo giờ Việt Nam: giờ 00:00 thuộc ngày hôm trước; AQI ngày = compute_aqi của PM trung bình ngày.
    Chu kỳ ngày chỉ dùng giờ đã đóng."""
    midnight = datetime(2026, 10, 14, 17, 0, tzinfo=UTC)  # 00:00 ngày 15/10 giờ Việt Nam
    from tests.unit.test_hourly_units import s

    def agg(hour, pm25, pm10):
        return aggregate_hour(hour, [s(hour, pm25=pm25, pm10=pm10)], 900, 1)

    async with get_sessionmaker()() as session:
        for hour, pm25, closed in (
            (midnight, 100.0, True),
            (midnight + timedelta(hours=1), 10.0, True),
            (midnight + timedelta(hours=2), 20.0, False),
        ):
            await repository.upsert_hour(session, node, agg(hour, pm25, 20.0), is_closed=closed, revision=0, at=hour)
        await session.commit()
        days = await service.series_day(session, node, midnight - timedelta(days=1), midnight + timedelta(days=1))
        prof = await service.profile(session, node, midnight - timedelta(days=30))
    assert [(d.day, d.n_hours, d.pm25) for d in days] == [(date(2026, 10, 14), 1, 100.0), (date(2026, 10, 15), 2, 15.0)]
    assert days[1].aqi == int(compute_aqi(15.0, 20.0))
    assert [(p.hour_of_day, p.n_hours) for p in prof] == [(0, 1), (1, 1)]  # giờ 02:00 đang mở nên không tính
    assert rows(db, "SELECT count(*) FROM node_hourly")[0][0] == 3
