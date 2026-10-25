"""Đường ống bước 3, 4 với dữ liệu thô thật (backend_design 7.1, 8.4–8.5, 18 "Đường ống giờ", "Chạy bù và độ mới",
"Không rò rỉ dữ liệu", "Revision và tái hiện").

Số đo thô sinh từ dataset.csv (1 mẫu mỗi giờ lúc h − 30 phút, nhận ngay lúc đo) cho node chu kỳ 1 giờ.
"""

from datetime import UTC, timedelta

import pandas as pd
import pytest
from sqlalchemy import text

from app.core import outbox, settings_store
from app.core.db import run_in_transaction
from app.core.timeutil import LOCAL_TZ
from app.modules.forecast import evaluate
from app.modules.forecast import service as forecast
from app.modules.hourly import service as hourly
from app.modules.mlruntime import adapter
from app.modules.pipeline import service as pipeline
from app.modules.telemetry.qc import QcFlag
from tests.integration.conftest import MODELS
from tests.integration.helpers import add_gateway, add_node, execute, rows, scalar
from tests.integration.test_forecast_run import dataset
from tests.integration.test_hourly_compute import add_measurement

H = timedelta(hours=1)
T0_LOCAL = pd.Timestamp("2026-09-22 18:00")
T0 = T0_LOCAL.tz_localize(LOCAL_TZ).tz_convert(UTC).to_pydatetime()
pytestmark = pytest.mark.skipif(not (MODELS / "v1-no_fill").is_dir(), reason="chưa có bundle model")


def insert_samples(engine, node_id: int, first_local: pd.Timestamp, last_local: pd.Timestamp) -> None:
    """Một số đo cho mỗi giờ của dataset trong [first, last] (giờ Việt Nam), đo lúc h − 30 phút."""
    d = dataset()
    part = d[(d["time"] >= first_local) & (d["time"] <= last_local)]
    params = []
    for r in part.itertuples():
        at = (r.time.tz_localize(LOCAL_TZ).tz_convert(UTC) - pd.Timedelta(minutes=30)).to_pydatetime()
        params.append({"n": node_id, "m": at, "pm25": r.pm2_5, "pm10": r.pm10, "t": r.Temperature, "h": r.Humidity})
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO measurements (node_id, gateway_id, seq, time_source, payload_hash, measured_at, "
                "received_at, trusted_at, qc_flags, pm25, pm10, temperature, humidity) "
                "VALUES (:n, 'GW_001', 0, 'received', 1, :m, :m, :m, 0, :pm25, :pm10, :t, :h)"
            ),
            params,
        )


@pytest.fixture
async def live(db, model):
    """Node chu kỳ 1 giờ có 110 giờ số đo tới T0 + 5 giờ; node_hourly đã đóng tới T0 − 1 giờ (như đã chạy từ lâu)."""
    add_gateway(db)
    node = add_node(db, 1, expected_interval_s=3600, interval_locked=True)
    insert_samples(db, node, T0_LOCAL - pd.Timedelta(hours=110), T0_LOCAL + pd.Timedelta(hours=5))
    for i in range(110, 0, -1):
        await hourly.close_hour(T0 - i * H, T0 - i * H + timedelta(minutes=3))
    return node


def runs(db):
    return rows(db, "SELECT input_hour, issue_kind, status, attempt_count FROM forecast_runs ORDER BY input_hour")


async def test_outage_catch_up_late_and_catchup_kinds(db, live):
    """Chạy lúc T0+5': on_time. Tắt 5 giờ, bật lúc T0+5h20': đủ 5 giờ theo thứ tự; giờ mới nhất `late`, 4 giờ trước
    `catchup` (as-of tại scheduled_for, R16: chạy bù muộn vẫn ok). Chạy lại không tạo bản ghi trùng."""
    assert await pipeline.run(T0 + timedelta(minutes=5)) == {"done": 1, "pending": 0}
    assert await pipeline.run(T0 + 5 * H + timedelta(minutes=20)) == {"done": 5, "pending": 0}
    assert runs(db) == [
        (T0, "on_time", "ok", 1),
        *[(T0 + i * H, "catchup", "ok", 1) for i in range(1, 5)],
        (T0 + 5 * H, "late", "ok", 1),
    ]
    kinds = rows(db, "SELECT forecast_kind FROM hour_pipeline WHERE hour_end >= :t ORDER BY hour_end", t=T0)
    assert [k.forecast_kind for k in kinds] == ["on_time", "catchup", "catchup", "catchup", "catchup", "late"]
    efs = rows(
        db, "SELECT r.input_hour, a.effective_now FROM forecast_attempts a JOIN forecast_runs r ON r.id = a.run_id"
    )
    for hour, effective in efs:
        if T0 < hour < T0 + 5 * H:
            assert effective == hour + timedelta(minutes=5)  # effective_now = scheduled_for khi chạy bù

    assert await pipeline.run(T0 + 5 * H + timedelta(minutes=30)) == {"done": 0, "pending": 0}
    assert scalar(db, "SELECT count(*) FROM forecast_runs") == 6
    assert scalar(db, "SELECT count(*) FROM forecasts") == 6 * 24


async def test_late_data_does_not_change_published_forecast(db, live):
    """Không rò rỉ: bản ghi muộn (nhận sau khi phát hành) vào giờ ≤ t làm tăng revision giờ đó, dự báo đã phát hành
    không đổi; chạy bù dùng as-of nên không thấy bản ghi đến sau scheduled_for."""
    await pipeline.run(T0 + timedelta(minutes=5))
    before = rows(db, "SELECT horizon_h, predicted_aqi FROM forecasts ORDER BY horizon_h")
    features = scalar(db, "SELECT features FROM forecast_inputs")

    late = T0 + timedelta(minutes=30)
    add_measurement(db, live, T0 - timedelta(minutes=10), received_at=late, pm25=400.0, pm10=400.0, temperature=30.0,
                    humidity=70.0)  # fmt: skip
    add_measurement(db, live, T0 + H - timedelta(minutes=5), received_at=T0 + 3 * H, pm25=400.0, pm10=400.0,
                    temperature=30.0, humidity=70.0)  # fmt: skip
    await run_in_transaction(lambda s: hourly.enqueue_recompute(s, live, T0))  # như ingest xếp hàng giờ đã đóng
    assert (await hourly.process_recompute_queue(T0 + H))["revised"] == 1
    assert scalar(db, "SELECT revision FROM node_hourly WHERE node_id = :n AND hour_end = :h", n=live, h=T0) == 1
    assert rows(db, "SELECT horizon_h, predicted_aqi FROM forecasts ORDER BY horizon_h") == before
    assert scalar(db, "SELECT features FROM forecast_inputs") == features

    # Chạy bù giờ T0+1 lúc T0+5h: bản ghi của giờ T0+1 nhận lúc T0+3h (sau scheduled_for T0+1h05) bị bỏ
    await pipeline.run(T0 + 5 * H + timedelta(minutes=20))
    history = scalar(
        db, "SELECT h.history FROM forecast_input_history h JOIN forecast_runs r ON r.id = h.run_id "
            "WHERE r.input_hour = :t", t=T0 + H,
    )  # fmt: skip
    hour_t = next(x for x in history if x["time"] == (T0_LOCAL + pd.Timedelta(hours=1)).isoformat())
    expected = dataset().set_index("time").loc[T0_LOCAL + pd.Timedelta(hours=1), "pm2_5"]
    assert hour_t["pm2_5"] == expected and hour_t["revision"] is None


async def test_evaluation_revision_and_accuracy(db, live):
    """Bước 3 điền actual_aqi khi giờ đích đóng; dữ liệu muộn làm giờ đích đổi revision → outbox → đánh giá lại và
    tính lại forecast_accuracy_daily (R8). Sự kiện chạy lại không đổi gì thêm."""
    await pipeline.run(T0 + timedelta(minutes=5))
    await pipeline.run(T0 + 3 * H + timedelta(minutes=5))  # giờ đích h=3 của dự báo T0 đã đóng
    target = T0 + 3 * H
    f = rows(db, "SELECT f.* FROM forecasts f JOIN forecast_runs r ON r.id = f.run_id "
                 "WHERE r.input_hour = :t AND f.horizon_h = 3", t=T0)[0]  # fmt: skip
    actual = scalar(db, "SELECT aqi FROM node_hourly WHERE node_id = :n AND hour_end = :h", n=live, h=target)
    assert (f.actual_aqi, f.actual_revision, f.evaluated_at is not None) == (actual, 0, True)
    acc = rows(db, "SELECT * FROM forecast_accuracy_daily WHERE horizon_h = 3 AND issue_kind = 'on_time'")
    assert len(acc) == 1 and acc[0].n == 1
    assert acc[0].sum_abs_err == pytest.approx(abs(f.predicted_aqi - actual))
    assert acc[0].n_persistence == 1 and acc[0].sum_abs_err_persistence == abs(f.persistence_aqi - actual)

    add_measurement(db, live, target - timedelta(minutes=5), received_at=target + H, pm25=300.0, pm10=300.0)
    await run_in_transaction(lambda s: hourly.enqueue_recompute(s, live, target))
    await hourly.process_recompute_queue(target + H)
    import app.main  # noqa: F401 — đăng ký handler outbox như khi chạy ứng dụng

    await outbox.dispatch_once()
    new_actual = scalar(db, "SELECT aqi FROM node_hourly WHERE node_id = :n AND hour_end = :h", n=live, h=target)
    f2 = rows(db, "SELECT actual_aqi, actual_revision FROM forecasts WHERE run_id = :r AND horizon_h = 3",
              r=f.run_id)[0]  # fmt: skip
    assert new_actual != actual and tuple(f2) == (new_actual, 1)
    acc2 = rows(db, "SELECT sum_abs_err FROM forecast_accuracy_daily WHERE horizon_h = 3 AND issue_kind = 'on_time'")
    assert acc2[0].sum_abs_err == pytest.approx(abs(f.predicted_aqi - new_actual))

    # Sự kiện cũ (revision 0) hoặc chạy lại cùng revision: không đổi gì
    assert await run_in_transaction(lambda s: evaluate.apply_revision(s, live, target, 0, target + H)) == 0
    assert await run_in_transaction(lambda s: evaluate.apply_revision(s, live, target, 1, target + H)) == 0


async def test_restart_between_step_3_and_4(db, live, monkeypatch):
    """Bước 4 lỗi (vd tiến trình chết): giờ đã đóng và đối chiếu giữ nguyên; lần sau chỉ làm tiếp bước 4."""
    real = forecast.run_hour

    async def crash(*_):
        raise RuntimeError("tiến trình chết")

    monkeypatch.setattr(forecast, "run_hour", crash)
    out = await pipeline.run(T0 + timedelta(minutes=5))
    assert out["failed_hour"] == T0.isoformat()
    [p] = rows(db, "SELECT * FROM hour_pipeline")
    assert (p.closed_at is not None, p.eval_done_at is not None, p.forecast_done_at, p.attempts) == (
        True,
        True,
        None,
        1,
    )
    closed_at = p.closed_at
    monkeypatch.setattr(forecast, "run_hour", real)
    assert await pipeline.run(T0 + timedelta(minutes=6)) == {"done": 1, "pending": 0}
    [p] = rows(db, "SELECT * FROM hour_pipeline")
    assert p.closed_at == closed_at and p.forecast_kind == "on_time" and p.last_error is None


async def test_forecast_waiting_retry_does_not_block_next_hours(db, live, monkeypatch):
    """Dự báo giờ T0 đang chờ thử lại thì giờ sau vẫn được đóng và đối chiếu (một node lỗi không chặn đường ống)."""

    def boom(*_):
        raise RuntimeError("model lỗi")

    monkeypatch.setattr(adapter, "predict", boom)
    assert await pipeline.run(T0 + timedelta(minutes=5)) == {"done": 0, "pending": 1}
    assert await pipeline.run(T0 + H + timedelta(minutes=5)) == {"done": 0, "pending": 2}
    p = {r.hour_end: r for r in rows(db, "SELECT * FROM hour_pipeline")}
    assert p[T0 + H].closed_at is not None and p[T0 + H].eval_done_at is not None
    assert p[T0].forecast_done_at is None and p[T0].last_error is None


async def test_catch_up_limit_marks_old_hours_skipped(db, live):
    """Bước 4 chỉ bù forecast_catchup_max_hours giờ gần nhất; giờ cũ hơn ghi forecast_kind = skipped."""
    execute(db, "INSERT INTO app_settings (key, value) VALUES ('forecast_catchup_max_hours', '2')")
    settings_store.clear_cache()
    await pipeline.run(T0 + timedelta(minutes=5))
    await pipeline.run(T0 + 5 * H + timedelta(minutes=20))
    kinds = rows(db, "SELECT hour_end, forecast_kind FROM hour_pipeline WHERE hour_end > :t ORDER BY hour_end", t=T0)
    assert [k.forecast_kind for k in kinds] == ["skipped", "skipped", "catchup", "catchup", "late"]
    assert scalar(db, "SELECT count(*) FROM forecast_runs") == 4


async def test_excluded_samples_flag_still_counted(db, live):
    """Bản ghi cách ly (Gateway chưa duyệt) không vào đầu vào dự báo: n_samples của giờ t chỉ tính mẫu tin cậy."""
    add_measurement(db, live, T0 - timedelta(minutes=20), flags=QcFlag.UNTRUSTED_GATEWAY, pm25=999.0, pm10=999.0)
    await pipeline.run(T0 + timedelta(minutes=5))
    run = rows(db, "SELECT input_t_samples, status FROM forecast_runs")[0]
    assert tuple(run) == (1, "ok")
