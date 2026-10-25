"""Trạm mô phỏng và nạp CSV (P10, backend_design 12.4 A10, 18) và mốc M3: node có ≥ 73 giờ ra được dự báo."""

from datetime import UTC, timedelta

import pandas as pd
import pytest

from app.core.timeutil import LOCAL_TZ, FixedClock, set_clock
from app.modules.pipeline import service as pipeline
from scripts import import_hourly_csv as importer
from tests.fixtures.firmware import telemetry
from tests.integration.conftest import MODELS
from tests.integration.helpers import add_gateway, add_node, rows, scalar
from tests.integration.test_forecast_run import dataset

END_LOCAL = pd.Timestamp("2026-10-15 14:00")  # dời dữ liệu để giờ cuối là 14:00 ngày 15/10
END = END_LOCAL.tz_localize(LOCAL_TZ).tz_convert(UTC).to_pydatetime()


@pytest.fixture
def csv_file(tmp_path):
    """120 giờ cuối của dataset.csv, đúng schema."""
    path = tmp_path / "sim.csv"
    dataset().tail(120).to_csv(path, index=False)
    return path


async def create(csv, *extra):
    args = importer.parse_args(["--create", "Mô phỏng Hà Nội", "--lat", "21.03", "--lng", "105.85", "--csv", str(csv),
                                "--end", str(END_LOCAL), *extra])  # fmt: skip
    return await importer.run(args)


async def test_create_and_import_is_idempotent(db, csv_file):
    out = await create(csv_file)
    assert out.startswith("ST001 (mô phỏng): thêm 120, cập nhật 0, không đổi 0 giờ")
    [node] = rows(db, "SELECT n.*, l.code AS network FROM nodes n JOIN lora_networks l ON l.id = n.lora_network_id")
    assert (node.is_simulated, node.status, node.is_public, node.network, node.registered_via) == (
        True, "active", True, "simulated", "admin",
    )  # fmt: skip
    last = rows(db, "SELECT hour_end, aqi, is_closed, revision FROM node_hourly ORDER BY hour_end DESC LIMIT 1")[0]
    assert (last.hour_end, last.aqi, last.is_closed, last.revision) == (END, int(dataset()["AQI"].iloc[-1]), True, 0)

    again = await importer.run(importer.parse_args(["--station", "st001", "--csv", str(csv_file), "--end",
                                                    str(END_LOCAL)]))  # fmt: skip
    assert "thêm 0, cập nhật 0, không đổi 120" in again


async def test_changed_value_is_a_revision(db, csv_file, tmp_path):
    await create(csv_file)
    changed = dataset().tail(120).copy()
    changed.iloc[-1, changed.columns.get_loc("AQI")] = 499
    path = tmp_path / "changed.csv"
    changed.to_csv(path, index=False)
    out = await importer.run(importer.parse_args(["--station", "ST001", "--csv", str(path), "--end", str(END_LOCAL)]))
    assert "cập nhật 1" in out
    assert scalar(db, "SELECT revision FROM node_hourly WHERE hour_end = :h", h=END) == 1
    assert scalar(db, "SELECT count(*) FROM outbox_events WHERE kind = 'hourly_revised'") == 1


async def test_refuses_real_station(db, csv_file):
    add_gateway(db)
    add_node(db, 1)
    with pytest.raises(importer.CsvImportError, match="không phải trạm mô phỏng"):
        await importer.run(importer.parse_args(["--station", "ST001", "--csv", str(csv_file)]))
    assert scalar(db, "SELECT count(*) FROM node_hourly") == 0


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.rename(columns={"AQI": "aqi"}), "Cột không khớp"),
        (lambda d: d.assign(time=d["time"] + pd.Timedelta(minutes=30)), "giờ tròn"),
        (lambda d: pd.concat([d, d.tail(1)]), "không trùng"),
        (lambda d: d.assign(AQI=d["AQI"] + 0.5), "số nguyên"),
        (lambda d: d.iloc[0:0], "không có dòng"),
    ],
)
def test_csv_validation(tmp_path, mutate, message):
    path = tmp_path / "bad.csv"
    mutate(dataset().tail(10)).to_csv(path, index=False)
    with pytest.raises(importer.CsvImportError, match=message):
        importer.read_hours(path)


def test_default_keeps_original_labels(csv_file):
    """Không truyền --end thì giữ nguyên nhãn giờ của CSV (không dời ngầm)."""
    hours = importer.read_hours(csv_file)
    assert hours[-1].hour_end == dataset()["time"].iloc[-1].tz_localize(LOCAL_TZ).tz_convert(UTC).to_pydatetime()


async def test_firmware_cannot_write_into_simulated_network(client, db, csv_file, clock):
    """Mạng `simulated` không có Gateway: NODE_001 qua GW_001 (mạng default) là node khác, trạm mô phỏng không đổi."""
    await create(csv_file)
    add_gateway(db)
    assert (await client.post("/api/v1/telemetry", json=telemetry())).status_code == 200
    sim = rows(db, "SELECT id FROM nodes WHERE is_simulated")[0].id
    assert scalar(db, "SELECT count(*) FROM measurements WHERE node_id = :n", n=sim) == 0
    assert scalar(db, "SELECT count(*) FROM nodes") == 2


@pytest.mark.skipif(not (MODELS / "v1-no_fill").is_dir(), reason="chưa có bundle model")
async def test_m3_gate_station_with_73_hours_gets_forecast(client, db, csv_file, model):
    """Mốc M3: trạm có ≥ 73 giờ liên tục → đường ống ra dự báo ok đủ 24 mốc; web và trợ lý ghi rõ trạm mô phỏng."""
    await create(csv_file)
    set_clock(FixedClock(END + timedelta(minutes=10)))
    assert await pipeline.run(END + timedelta(minutes=5)) == {"done": 1, "pending": 0}
    run = rows(db, "SELECT status, issue_kind FROM forecast_runs")[0]
    assert tuple(run) == ("ok", "on_time")
    public = (await client.get("/api/v1/public/stations/ST001/forecast")).json()
    assert public["status"] == "ok" and len(public["forecast"]["items"]) == 24
    assert (await client.get("/api/v1/public/stations/ST001")).json()["is_simulated"] is True
    a = (await client.get("/api/v1/assistant/stations/ST001/forecast",
                          headers={"Authorization": "Bearer test-assistant-token"})).json()  # fmt: skip
    assert a["station"]["is_simulated"] is True and "trạm mô phỏng" in a["summary_vi"]
