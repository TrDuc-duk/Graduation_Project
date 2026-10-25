"""Bước dự báo (backend_design 8.4, 18 "Golden ML qua DB", "Lần chạy và lần thử", "Giờ t thiếu").

Golden: nạp một đoạn `ml/data/dataset.csv` vào `node_hourly` qua repository thật (SQLAlchemy + psycopg, đổi giờ
UTC ↔ Việt Nam), chạy bước dự báo, so với `src.predict.predict` trên chính CSV đó.
"""

import asyncio
import time
from datetime import UTC, timedelta
from pathlib import Path

import pandas as pd
import pytest
from src.data_loading import load_raw_dataset
from src.predict import predict as ml_predict

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.timeutil import LOCAL_TZ
from app.modules.forecast import service
from app.modules.hourly import repository as hourly_repo
from app.modules.hourly.aggregate import HourAggregate
from app.modules.mlruntime import adapter
from app.modules.mlruntime.registry import registry
from tests.integration.helpers import add_gateway, add_node, execute, rows, scalar

REPO = Path(__file__).resolve().parents[3]
MODELS = REPO / "models" / "xgb"
T_LOCAL = pd.Timestamp("2026-09-22 23:00")  # giờ cuối của dataset
T = T_LOCAL.tz_localize(LOCAL_TZ).tz_convert(UTC).to_pydatetime()  # 16:00 UTC
NOW = T + timedelta(minutes=5)  # phát hành đúng hạn (scheduled_for = t + 3' + 2')
H = timedelta(hours=1)
pytestmark = pytest.mark.skipif(not (MODELS / "v1-no_fill").is_dir(), reason="chưa có bundle model")

_DATASET: pd.DataFrame | None = None


def dataset() -> pd.DataFrame:
    """dataset.csv (đọc một lần cho cả file test)."""
    global _DATASET
    if _DATASET is None:
        _DATASET = load_raw_dataset()
    return _DATASET


@pytest.fixture
async def model(db, monkeypatch):
    """Model v1-no_fill active (registry dùng chung của tiến trình); dọn trạng thái nạp sau test."""
    monkeypatch.setenv("MODEL_DIR", str(MODELS))
    get_settings.cache_clear()
    await registry.rescan()
    yield registry.current()
    registry._loaded = None
    get_settings.cache_clear()


@pytest.fixture
def node(db):
    add_gateway(db)
    return add_node(db, 1, expected_interval_s=3600, interval_locked=True)


async def load_hours(node_id: int, end_local: pd.Timestamp, hours: int, drop: set | None = None) -> None:
    """Nạp `hours` dòng giờ của dataset kết thúc ở `end_local` vào node_hourly (đã đóng, revision 0)."""
    d = dataset()
    part = d[(d["time"] > end_local - pd.Timedelta(hours=hours)) & (d["time"] <= end_local)]
    async with get_sessionmaker()() as session:
        for r in part.itertuples():
            if drop and r.time in drop:
                continue
            hour = r.time.tz_localize(LOCAL_TZ).tz_convert(UTC).to_pydatetime()
            agg = HourAggregate(
                hour_end=hour, n_samples=1, n_excluded=0, n_time_estimated=0, n_time_ambiguous=0,
                expected_samples=1.0, coverage=1.0, n_pm25=1, n_pm10=1, n_temperature=1, n_humidity=1, n_co2=0,
                pm25_avg=_v(r.pm2_5), pm10_avg=_v(r.pm10), temperature_avg=_v(r.Temperature),
                humidity_avg=_v(r.Humidity), co2_avg=None, tvoc_avg=None, pm25_max=None, pm10_max=None,
                aqi=None if pd.isna(r.AQI) else int(r.AQI), aqi_pm25=None, aqi_pm10=None, qc_flags=0,
            )  # fmt: skip
            await hourly_repo.upsert_hour(session, node_id, agg, is_closed=True, revision=0, at=hour)
        await session.commit()


def _v(x: float) -> float | None:
    return None if pd.isna(x) else float(x)


def run_row(db):
    return rows(db, "SELECT * FROM forecast_runs ORDER BY id")


async def test_golden_through_db_matches_src_predict(db, model, node):
    """24 mốc dự báo qua DB thật trùng `src.predict.predict` trên CSV gốc (lệch < 1e-9; thực tế bằng nhau)."""
    await load_hours(node, T_LOCAL, 120)
    assert await service.run_node(node, T, NOW) == "ok"
    stored = rows(db, "SELECT horizon_h, predicted_aqi, persistence_aqi, target_hour FROM forecasts ORDER BY horizon_h")
    expected = ml_predict(dataset(), t=T_LOCAL, now=T_LOCAL + pd.Timedelta(minutes=5), models_dir=MODELS / "v1-no_fill")
    assert [r.horizon_h for r in stored] == list(expected["horizon_hours"]) == list(range(3, 73, 3))
    for r, e in zip(stored, expected["predicted_aqi"], strict=True):
        assert abs(r.predicted_aqi - e) < 1e-9
    assert {r.persistence_aqi for r in stored} == {181}  # cột AQI của hàng feature tại t (R34)
    assert stored[0].target_hour == T + 3 * H

    [run] = run_row(db)
    assert (run.status, run.issue_kind, run.trigger, run.attempt_count) == ("ok", "on_time", "schedule", 1)
    assert run.input_hour == T and NOW <= run.issued_at < NOW + timedelta(seconds=30)
    assert (run.input_t_samples, run.input_t_coverage, run.input_t_revision) == (1, 1.0, 0)
    assert run.input_convention == "end_label_provisional" and run.issued_at is not None
    assert run.scheduled_for == T + timedelta(minutes=5) and run.input_cutoff_at == NOW
    [attempt] = rows(db, "SELECT * FROM forecast_attempts")
    assert (attempt.status, attempt.effective_now, attempt.started_at) == ("ok", NOW, NOW)
    [inp] = rows(db, "SELECT * FROM forecast_inputs")
    assert len(inp.features) == 184 and inp.model_id == model.model_id
    n_hist = scalar(db, "SELECT jsonb_array_length(history) FROM forecast_input_history")
    assert n_hist == 98  # dòng giờ có nhãn trong [t − 97 giờ, t] (required 73 + 24)


async def test_ok_run_is_frozen(db, model, node):
    await load_hours(node, T_LOCAL, 100)
    await service.run_node(node, T, NOW)
    assert await service.run_node(node, T, NOW + timedelta(minutes=1)) == "ok"
    assert scalar(db, "SELECT count(*) FROM forecast_attempts") == 1
    assert scalar(db, "SELECT count(*) FROM forecasts") == 24


async def test_late_issue_kind(db, model, node):
    """Giờ đóng mới nhất nhưng thực thi trễ hơn scheduled_for + forecast_late_after_s (10 phút) → late."""
    await load_hours(node, T_LOCAL, 100)
    now = T + timedelta(minutes=15, seconds=1)
    assert await service.run_node(node, T, now) == "ok"
    assert run_row(db)[0].issue_kind == "late"


async def test_catchup_reads_as_of_scheduled_for(db, model, node):
    """Giờ cũ hơn giờ đóng mới nhất → catchup, effective_now = scheduled_for, dữ liệu tính lại từ số đo thô as-of.
    Ở đây node_hourly có dữ liệu nhưng không có số đo thô nên as-of không có gì → no_data (không dùng node_hourly)."""
    await load_hours(node, T_LOCAL, 100)
    status = await service.run_node(node, T - 3 * H, NOW)
    [run] = run_row(db)
    assert (status, run.issue_kind, run.input_cutoff_at) == ("no_data", "catchup", T - 3 * H + timedelta(minutes=5))
    assert rows(db, "SELECT effective_now FROM forecast_attempts")[0].effective_now == run.scheduled_for


async def test_insufficient_history_with_readiness_and_no_retry(db, model, node):
    """Thiếu lịch sử (no_fill): missing_hours, eta_hours; không tự thử lại (cùng mốc cắt thì kết quả không đổi)."""
    await load_hours(node, T_LOCAL, 50)  # có 50 giờ, cần 73
    assert await service.run_node(node, T, NOW) == "insufficient_history"
    [run] = run_row(db)
    assert (run.missing_hours, run.eta_hours) == (23, 23)
    assert await service.run_node(node, T, NOW + timedelta(minutes=30)) == "insufficient_history"
    assert (
        scalar(db, "SELECT count(*) FROM forecast_attempts") == 1 and scalar(db, "SELECT count(*) FROM forecasts") == 0
    )


async def test_missing_hour_t_adds_nan_row(db, model, node):
    """Giờ t không có dòng nào: thêm dòng NaN (P3) → no_fill ra insufficient_history, giờ thiếu mới nhất là t."""
    await load_hours(node, T_LOCAL, 100, drop={T_LOCAL})
    assert await service.run_node(node, T, NOW) == "insufficient_history"
    assert (run_row(db)[0].missing_hours, run_row(db)[0].eta_hours) == (1, 73)


async def test_no_data(db, model, node):
    assert await service.run_node(node, T, NOW) == "no_data"


async def test_error_retries_with_backoff_then_gives_up(db, model, node, monkeypatch):
    """Lỗi hệ thống: thử lại sau 2, 4 phút; tổng tối đa 3 lần thử (R22)."""
    await load_hours(node, T_LOCAL, 100)

    def boom(*_):
        raise RuntimeError("model hỏng")

    monkeypatch.setattr(adapter, "predict", boom)
    assert await service.run_node(node, T, NOW) == "error"
    assert run_row(db)[0].next_attempt_at is not None
    assert await service.run_node(node, T, NOW + timedelta(minutes=1)) == "waiting"
    assert await service.run_node(node, T, NOW + timedelta(minutes=3)) == "error"
    assert await service.run_node(node, T, NOW + timedelta(minutes=10)) == "error_final"
    assert await service.run_node(node, T, NOW + timedelta(hours=1)) == "error_final"
    assert rows(db, "SELECT attempt_no, status FROM forecast_attempts ORDER BY attempt_no") == [
        (1, "error"), (2, "error"), (3, "error"),
    ]  # fmt: skip
    assert "model hỏng" in run_row(db)[0].reason


async def test_retry_success_recomputes_issue_kind(db, model, node, monkeypatch):
    """Lần thử đầu lỗi, lần sau thành công sau ngưỡng late → ghi late."""
    await load_hours(node, T_LOCAL, 100)
    real = adapter.predict
    calls = []

    def flaky(*args):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("tạm lỗi")
        return real(*args)

    monkeypatch.setattr(adapter, "predict", flaky)
    assert await service.run_node(node, T, NOW) == "error"
    assert await service.run_node(node, T, T + timedelta(minutes=16)) == "ok"
    [run] = run_row(db)
    assert (run.issue_kind, run.attempt_count) == ("late", 2)


async def test_manual_runs_are_separate(db, model, node):
    await load_hours(node, T_LOCAL, 100)
    for _ in range(2):
        assert await service.run_node(node, T, NOW, trigger="manual") == "ok"
    assert [(r.trigger, r.issue_kind) for r in run_row(db)] == [("manual", "manual")] * 2
    assert scalar(db, "SELECT count(*) FROM forecasts") == 48


async def test_stuck_attempt_is_retried(db, model, node):
    """Lần thử 'running' quá 10 phút (tiến trình chết giữa chừng) → đánh dấu lỗi rồi thử lại."""
    await load_hours(node, T_LOCAL, 100)
    execute(
        db,
        "INSERT INTO forecast_runs (node_id, model_id, trigger, issue_kind, input_hour, scheduled_for, input_cutoff_at,"
        " started_at, status, attempt_count) VALUES (:n, :m, 'schedule', 'on_time', :t, :s, :s, :s, 'running', 1)",
        n=node, m=model.model_id, t=T, s=NOW,
    )  # fmt: skip
    execute(db, "INSERT INTO forecast_attempts (run_id, attempt_no, started_at, effective_now, input_cutoff_at, "
                "status) VALUES (1, 1, :s, :s, :s, 'running')", s=NOW)  # fmt: skip
    assert await service.run_node(node, T, NOW + timedelta(minutes=5)) == "busy"
    assert await service.run_node(node, T, NOW + timedelta(minutes=11)) == "ok"
    assert rows(db, "SELECT attempt_no, status FROM forecast_attempts ORDER BY attempt_no") == [(1, "error"), (2, "ok")]


async def test_no_model(db, node):
    registry._loaded = None
    assert await service.run_node(node, T, NOW) == "no_model"
    assert (await service.run_hour(T, NOW)) == {"done": True, "skipped": "no_model"}


async def test_one_node_failure_does_not_block_others(db, model, node, monkeypatch):
    other = add_node(db, 2, expected_interval_s=3600, interval_locked=True)
    add_node(db, 3, forecast_enabled=False)  # không dự báo
    await load_hours(node, T_LOCAL, 100)
    await load_hours(other, T_LOCAL, 100)
    real = adapter.predict

    def fail_first_node(bundle, frame, t, now):
        if not hasattr(fail_first_node, "seen"):
            fail_first_node.seen = True
            raise RuntimeError("node 1 lỗi")
        return real(bundle, frame, t, now)

    monkeypatch.setattr(adapter, "predict", fail_first_node)
    out = await service.run_hour(T, NOW)
    assert (out["done"], out.get("error"), out.get("ok")) == (False, 1, 1)
    assert [(r.node_id, r.status) for r in run_row(db)] == [(node, "error"), (other, "ok")]


async def test_inference_runs_in_thread(db, model, node, monkeypatch):
    """Tính toán chạy trong thread: event loop vẫn chạy việc khác trong lúc model đang tính."""
    await load_hours(node, T_LOCAL, 100)
    real = adapter.predict

    def slow(*args):
        time.sleep(0.3)
        return real(*args)

    monkeypatch.setattr(adapter, "predict", slow)
    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    task = asyncio.create_task(ticker())
    try:
        assert await service.run_node(node, T, NOW) == "ok"
    finally:
        task.cancel()
    assert ticks >= 10
