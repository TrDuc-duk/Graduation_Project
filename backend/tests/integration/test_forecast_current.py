"""Dự báo hiện hành và API dự báo (backend_design 11.5, 18 "Dự báo cũ (R23)", "Sai số hiển thị (R15)").

Lần chạy và mốc dự báo được ghi thẳng vào DB để kiểm tra quy tắc chọn/trạng thái mà không phụ thuộc model.
"""

import json
from datetime import timedelta

import pytest
from sqlalchemy import text

from tests.conftest import T0
from tests.integration.helpers import add_gateway, execute
from tests.integration.test_public_api import HN, station

API = "/api/v1/public/stations/ST001/forecast"
H = timedelta(hours=1)
SUMMARY = {str(h): {"n_trees": 100, "test_mae": 17.5 + h / 10} for h in range(3, 73, 3)}


@pytest.fixture
def setup(db, clock):
    """ST001 công khai, model id 1 (MAE test theo horizon). Đồng hồ ở 14:20 giờ Việt Nam."""
    add_gateway(db)
    node = station(db, 1, HN)
    execute(
        db,
        "INSERT INTO ml_models (dir_name, model_version, bundle_sha256, horizons, nan_policy, required_history_hours, "
        "feature_count, feature_columns_sha256, summary, is_active) VALUES ('v1-no_fill', 'v1', 'sha', "
        "'{3,6}', 'no_fill', 73, 184, 'f', CAST(:s AS jsonb), true)",
        s=json.dumps(SUMMARY),
    )
    clock.at = T0 + timedelta(minutes=20)
    return node


def run(db, node: int, input_hour, *, status="ok", kind="on_time", missing=None, eta=None, reason=None) -> int:
    """Ghi một lần chạy (và 24 mốc AQI 100 + h nếu `ok`)."""
    with_issue = status == "ok"
    run_id = insert_returning(
        db,
        "INSERT INTO forecast_runs (node_id, model_id, trigger, issue_kind, input_hour, scheduled_for, "
        "input_cutoff_at, started_at, issued_at, status, missing_hours, eta_hours, reason, input_t_coverage) "
        "VALUES (:n, 1, :trig, :k, :t, :s, :s, :s, :issued, :st, :m, :e, :r, 1.0) RETURNING id",
        n=node,
        trig="manual" if kind == "manual" else "schedule",
        k=kind,
        t=input_hour,
        s=input_hour + timedelta(minutes=5),
        issued=input_hour + timedelta(minutes=5) if with_issue else None,
        st=status,
        m=missing,
        e=eta,
        r=reason,
    )
    if with_issue:
        for h in range(3, 73, 3):
            execute(
                db,
                "INSERT INTO forecasts (run_id, horizon_h, node_id, input_hour, target_hour, predicted_aqi, "
                "persistence_aqi) VALUES (:r, :h, :n, :t, :tt, :p, 100)",
                r=run_id, h=h, n=node, t=input_hour, tt=input_hour + h * H, p=100.4 + h,
            )  # fmt: skip
    return run_id


def insert_returning(engine, sql: str, **params):
    """INSERT … RETURNING trong transaction có commit."""
    with engine.begin() as conn:
        return conn.scalar(text(sql), params)


async def get(client, **params):
    return (await client.get(API, params=params)).json()


async def test_ok_forecast_with_confidence_and_training_error(client, db, setup):
    run(db, setup, T0)
    f = await get(client)
    assert (f["station_id"], f["status"], f["message"]) == ("ST001", "ok", None)
    assert f["freshness"] == {"age_hours": 0, "expected_input_hour": "2026-10-15T14:00:00+07:00"}
    body = f["forecast"]
    assert (body["model_version"], body["input_hour"], body["issued_at"]) == (
        "v1",
        "2026-10-15T14:00:00+07:00",
        "2026-10-15T14:05:00+07:00",
    )
    assert (body["issue_kind"], body["input_coverage"]) == ("on_time", 1.0)
    items = {i["horizon_h"]: i for i in body["items"]}
    assert len(items) == 24
    assert items[3] == {"horizon_h": 3, "target_time": "2026-10-15T17:00:00+07:00", "aqi": 103, "level": "usg",
                        "confidence": "high", "typical_error": 17.8, "error_source": "training"}  # fmt: skip
    assert (items[24]["confidence"], items[27]["confidence"], items[72]["confidence"]) == ("medium", "low", "low")
    keys = json.dumps(f)
    assert all(word not in keys for word in ("lower", "upper", "interval", "reason"))  # không có "khoảng" (R15)


async def test_horizon_filter_and_validation(client, db, setup):
    run(db, setup, T0)
    assert [i["horizon_h"] for i in (await get(client, horizons="6,3,6"))["forecast"]["items"]] == [3, 6]
    r = await client.get(API, params={"horizons": "4"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_PARAMS"


async def test_grace_window_keeps_ok_until_quarter_past(client, db, setup, clock):
    """14:00–14:15 vẫn ok với dự báo 13:00 (due_hour chưa sang giờ mới); 14:16 thành stale 1 giờ."""
    run(db, setup, T0 - H)
    clock.at = T0 + timedelta(minutes=10)
    assert (await get(client))["status"] == "ok"
    clock.at = T0 + timedelta(minutes=16)
    f = await get(client)
    assert (f["status"], f["freshness"]["age_hours"], f["message"]) == ("stale", 1, "Dự báo từ 1 giờ trước.")


async def test_stale_three_hours_shows_only_future_items(client, db, setup, clock):
    """Lần chạy mới nhất thiếu dữ liệu, bản thành công cách 3 giờ → stale, chỉ các mốc tương lai, kèm readiness."""
    run(db, setup, T0)
    run(db, setup, T0 + 3 * H, status="insufficient_history", missing=2, eta=72, reason="Thiếu lịch sử /models/x")
    clock.at = T0 + 3 * H + timedelta(minutes=20)
    f = await get(client)
    assert (f["status"], f["freshness"]["age_hours"]) == ("stale", 3)
    assert f["message"] == "Dự báo từ 3 giờ trước; lần cập nhật gần nhất thiếu dữ liệu."
    assert [i["horizon_h"] for i in f["forecast"]["items"]][0] == 6  # mốc 3 giờ (17:00) đã qua
    assert f["latest_attempt"] == {
        "input_hour": "2026-10-15T17:00:00+07:00",
        "status": "insufficient_history",
        "readiness": {"required_hours": 73, "missing_hours": 2, "eta_hours": 72},
    }
    assert "/models/x" not in json.dumps(f)  # lý do nội bộ chỉ Admin thấy


async def test_older_than_six_hours_hides_numbers(client, db, setup, clock):
    run(db, setup, T0)
    run(db, setup, T0 + 7 * H, status="insufficient_history", missing=18, eta=18)
    clock.at = T0 + 7 * H + timedelta(minutes=20)
    f = await get(client)
    assert (f["status"], f["forecast"]) == ("insufficient_history", None)
    assert f["message"] == "Trạm cần 73 giờ dữ liệu liên tục để dự báo, còn khoảng 18 giờ nữa."
    en = (await client.get(API, headers={"Accept-Language": "en"})).json()
    assert en["message"].startswith("The station needs 73 hours")


async def test_worker_stopped_ages_by_clock(client, db, setup, clock):
    """R31: worker dừng sau dự báo 14:00 — lúc 21:10 due_hour = 20:00 → stale 6 giờ; lúc 21:16 → quá 6 giờ, ẩn số."""
    run(db, setup, T0)
    clock.at = T0 + 7 * H + timedelta(minutes=10)
    f = await get(client)
    assert (f["status"], f["freshness"]["age_hours"]) == ("stale", 6)
    clock.at = T0 + 7 * H + timedelta(minutes=16)
    f = await get(client)
    assert (f["status"], f["forecast"], f["freshness"]["age_hours"]) == ("unavailable", None, 7)


async def test_catchup_is_never_current(client, db, setup):
    run(db, setup, T0, kind="catchup")
    f = await get(client)
    assert (f["status"], f["forecast"]) == ("unavailable", None)
    assert f["message"] == "Chưa có dự báo cho trạm này."


async def test_no_runs_and_error_status(client, db, setup):
    assert (await get(client))["status"] == "unavailable"
    run(db, setup, T0, status="error", reason="Traceback lỗi DB")
    f = await get(client)
    assert (f["status"], f["message"]) == ("error", "Dự báo tạm thời chưa cập nhật được.")
    assert "Traceback" not in json.dumps(f)


async def test_live_error_after_50_pairs(client, db, setup):
    """Mốc có ≥ 50 cặp đối chiếu trong 30 ngày dùng MAE thực tế (error_source live)."""
    run(db, setup, T0)
    execute(
        db,
        "INSERT INTO forecast_accuracy_daily (node_id, model_id, horizon_h, day, issue_kind, n, sum_abs_err, "
        "sum_sq_err, sum_err, sum_abs_err_persistence, n_persistence) VALUES "
        "(:n, 1, 3, '2026-10-14', 'on_time', 50, 600, 0, 0, 0, 0), "
        "(:n, 1, 6, '2026-10-14', 'on_time', 49, 600, 0, 0, 0, 0)",
        n=setup,
    )  # fmt: skip
    items = {i["horizon_h"]: i for i in (await get(client))["forecast"]["items"]}
    assert (items[3]["typical_error"], items[3]["error_source"]) == (12.0, "live")
    assert items[6]["error_source"] == "training"


async def test_unknown_station(client, db, setup):
    assert (await client.get("/api/v1/public/stations/ST404/forecast")).status_code == 404


async def test_assistant_forecast_same_numbers_as_public(client, db, setup):
    """API trợ lý đọc cùng dự báo đã lưu (mặc định 3, 6, 12, 24 giờ); mốc độ tin cậy thấp đọc là xu hướng."""
    run(db, setup, T0)
    headers = {"Authorization": "Bearer test-assistant-token"}
    a = (await client.get("/api/v1/assistant/stations/ST001/forecast", headers=headers)).json()
    public = {i["horizon_h"]: i["aqi"] for i in (await get(client))["forecast"]["items"]}
    assert (a["status"], a["horizons"]) == ("ok", [3, 6, 12, 24])
    assert {i["horizon_h"]: i["aqi"] for i in a["forecast"]["items"]} == {h: public[h] for h in (3, 6, 12, 24)}
    assert "Sau 3 giờ, lúc 17:00: AQI khoảng 103" in a["summary_vi"] and "14:05 ngày 15/10" in a["summary_vi"]
    low = await client.get("/api/v1/assistant/stations/ST001/forecast", params={"horizons": "48"}, headers=headers)
    assert "chỉ là xu hướng" in low.json()["summary_vi"]

    execute(db, "DELETE FROM forecasts")
    execute(db, "DELETE FROM forecast_runs")
    none = (await client.get("/api/v1/assistant/stations/ST001/forecast", headers=headers)).json()
    assert (none["status"], none["forecast"]) == ("unavailable", None)
    assert "Không có con số dự báo nào để đọc" in none["summary_vi"]
