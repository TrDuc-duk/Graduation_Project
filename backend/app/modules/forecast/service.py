"""Bước dự báo (bước 4 của đường ống giờ, backend_design 8.4) và lần chạy / lần thử (R22).

Một lần thực thi chia ba transaction ngắn:
1. nhận lần thử: tạo hoặc khóa lần chạy, ghi `forecast_attempts`, chụp dữ liệu giờ đầu vào (kèm revision);
2. chạy model trong thread (không giữ session, không giữ khóa DB);
3. ghi kết quả nếu lần thử vẫn là lần thử hiện hành của lần chạy.

Mốc cắt dữ liệu: `on_time` / `late` / `manual` đọc `node_hourly` lúc thực thi (`input_cutoff_at = effective_now`
= thời điểm đọc); chỉ `catchup` dùng `hourly_as_of(cutoff = scheduled_for)` và `effective_now = scheduled_for`.
"""

import logging
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import anyio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events, settings_store
from app.core.db import run_in_transaction
from app.core.scheduler import PROCESS_ID
from app.modules.devices import service as devices
from app.modules.devices.models import Node
from app.modules.forecast import repository
from app.modules.forecast.inputs import HourRow, history_frame, history_records, local_naive, readiness, sha256_json
from app.modules.forecast.models import ForecastRun
from app.modules.hourly import service as hourly
from app.modules.mlruntime import adapter
from app.modules.mlruntime.registry import LoadedBundle, registry

log = logging.getLogger(__name__)

HOUR = timedelta(hours=1)
PUBLISH_DELAY = timedelta(seconds=120)  # scheduled_for = t + hour_close_grace_s + 120 giây
STUCK_AFTER = timedelta(minutes=10)  # lần thử "running" quá lâu (tiến trình chết) được coi là lỗi
FINAL = ("ok", "insufficient_history", "no_data")
PUBLISHED_KINDS = ("on_time", "late", "manual")


@dataclass
class Claim:
    """Lần thử vừa nhận: đủ thông tin để chạy model mà không cần session."""

    run_id: int
    attempt_id: int
    attempt_no: int
    node: Node
    bundle: LoadedBundle
    t: datetime
    issue_kind: str
    effective_now: datetime
    started_at: datetime  # thời điểm thực thi thật của lần thử (`now` lúc nhận)
    rows: list[HourRow] = field(default_factory=list)


@dataclass(frozen=True)
class Outcome:
    """Kết quả tính toán của một lần thử."""

    status: str  # ok | insufficient_history | no_data | error
    preds: dict[int, float] | None = None
    features: list[float] | None = None
    persistence: int | None = None
    reason: str | None = None
    missing_hours: int | None = None
    eta_hours: int | None = None


async def scheduled_for(t: datetime) -> datetime:
    """Thời điểm phát hành theo kế hoạch của giờ t."""
    grace = await settings_store.get("hour_close_grace_s")
    return t + timedelta(seconds=grace) + PUBLISH_DELAY


async def hour_issue_kind(t: datetime, now: datetime) -> str:
    """Loại phát hành của giờ t khi chạy lúc `now` (on_time/late/catchup) cho `hour_pipeline.forecast_kind`."""
    late_after = await settings_store.get("forecast_late_after_s")
    return (await _issue_kind(t, now, await scheduled_for(t), "schedule", late_after))[0]


async def run_hour(t: datetime, now: datetime) -> dict:
    """Bước 4 cho giờ t: dự báo mọi node `active` + `forecast_enabled`. Một node lỗi không chặn node khác.

    Trả thống kê và `done` = mọi node đã có lần chạy ở trạng thái kết thúc (ok / thiếu dữ liệu / lỗi hết lượt).
    """
    if registry.current() is None:
        return {"done": True, "skipped": "no_model"}
    nodes = await run_in_transaction(devices.forecast_nodes)
    stats: dict[str, int] = {}
    for node in nodes:
        try:
            status = await run_node(node.id, t, now)
        except Exception:  # noqa: BLE001 — một node lỗi không chặn node khác (đã ghi vào forecast_runs)
            log.exception("Dự báo node %s giờ %s lỗi", node.id, t)
            status = "error"
        stats[status] = stats.get(status, 0) + 1
    pending = {k: v for k, v in stats.items() if k not in (*FINAL, "error_final")}
    return {"done": not pending, **stats}


async def run_node(
    node_id: int, t: datetime, now: datetime, *, trigger: str = "schedule", user_id: int | None = None
) -> str:
    """Một lần thực thi cho (node, giờ t). Trả trạng thái: ok, insufficient_history, no_data, error (còn lượt),
    error_final (hết lượt), waiting (chưa tới giờ thử lại), busy (tiến trình khác đang chạy), no_model.
    """
    claim = await run_in_transaction(lambda s: _claim(s, node_id, t, now, trigger, user_id))
    if isinstance(claim, str):
        return claim
    started = time.perf_counter()
    try:
        outcome = await anyio.to_thread.run_sync(_compute, claim)
    except Exception as exc:  # noqa: BLE001 — lỗi hệ thống/model: thử lại theo R22
        log.exception("Model lỗi node %s giờ %s", node_id, t)
        outcome = Outcome("error", reason=f"{type(exc).__name__}: {exc}"[:500])
    duration_ms = int((time.perf_counter() - started) * 1000)
    return await run_in_transaction(lambda s: _finish(s, claim, outcome, duration_ms))


async def _claim(
    session: AsyncSession, node_id: int, t: datetime, now: datetime, trigger: str, user_id: int | None
) -> Claim | str:
    """Tạo hoặc khóa lần chạy, quyết định có được thử tiếp không, ghi lần thử và chụp dữ liệu đầu vào."""
    bundle = registry.current()
    if bundle is None:
        return "no_model"
    node = await devices.get_node(session, node_id)
    if node is None:
        return "no_data"
    settings = await settings_store.get_many("forecast_late_after_s", "forecast_max_attempts")
    planned = await scheduled_for(t)
    kind, effective_now = await _issue_kind(t, now, planned, trigger, settings["forecast_late_after_s"])

    if trigger == "schedule":
        run = await repository.lock_scheduled_run(session, node_id, bundle.model_id, t)
        if run is None:
            if await repository.scheduled_run_exists(session, node_id, bundle.model_id, t):
                return "busy"  # tiến trình khác đang giữ dòng
            run = await _new_run(session, node, bundle, t, planned, kind, effective_now, trigger, user_id, now)
            if run is None:
                return "busy"
        else:
            if run.status == "running":  # lần thử trước chưa xong: còn chạy, hay tiến trình đã chết?
                last = await repository.latest_attempt(session, run.id)
                if last is not None and now - last.started_at < STUCK_AFTER:
                    return "busy"
                if last is not None:
                    last.status, last.finished_at, last.reason = "error", now, "Lần thử bị gián đoạn"
                run.status = "error"
            verdict = _retry_verdict(run, now, settings["forecast_max_attempts"])
            if verdict is not None:
                return verdict
    else:
        run = await _new_run(session, node, bundle, t, planned, kind, effective_now, trigger, user_id, now)

    run.attempt_count += 1
    run.status, run.issue_kind, run.input_cutoff_at, run.next_attempt_at = "running", kind, effective_now, None
    attempt_id = await repository.add_attempt(
        session, run_id=run.id, attempt_no=run.attempt_count, started_at=now, effective_now=effective_now,
        input_cutoff_at=effective_now, status="running", process_id=PROCESS_ID,
    )  # fmt: skip
    rows = await _snapshot(session, node, bundle, t, kind, effective_now)
    return Claim(run.id, attempt_id, run.attempt_count, node, bundle, t, kind, effective_now, now, rows)


async def _issue_kind(
    t: datetime, now: datetime, planned: datetime, trigger: str, late_after_s: int
) -> tuple[str, datetime]:
    """Loại phát hành và `effective_now` (bảng ở backend_design 8.4)."""
    if trigger == "manual":
        return "manual", now
    if t == await hourly.latest_closable_hour(now):
        return ("on_time" if now <= planned + timedelta(seconds=late_after_s) else "late"), now
    return "catchup", planned


async def _new_run(
    session: AsyncSession, node: Node, bundle: LoadedBundle, t: datetime, planned: datetime, kind: str,
    effective_now: datetime, trigger: str, user_id: int | None, now: datetime,
) -> ForecastRun | None:  # fmt: skip
    """Tạo lần chạy mới ở trạng thái running (trùng lần chạy theo lịch → None)."""
    return await repository.insert_run(
        session, node_id=node.id, model_id=bundle.model_id, trigger=trigger, issue_kind=kind, triggered_by=user_id,
        input_hour=t, scheduled_for=planned, input_cutoff_at=effective_now, started_at=now, status="running",
        attempt_count=0,
    )  # fmt: skip


def _retry_verdict(run: ForecastRun, now: datetime, max_attempts: int) -> str | None:
    """None nếu được thử tiếp; ngược lại trạng thái trả về. Lần chạy `ok` đóng băng; thiếu dữ liệu không tự thử lại."""
    if run.status in FINAL:
        return run.status
    if run.attempt_count >= max_attempts:
        return "error_final"
    if run.status == "error" and run.next_attempt_at is not None and now < run.next_attempt_at:
        return "waiting"
    return None


async def _snapshot(
    session: AsyncSession, node: Node, bundle: LoadedBundle, t: datetime, kind: str, effective_now: datetime
) -> list[HourRow]:
    """Chụp các dòng giờ có nhãn trong [t − (required + 24) giờ, t]; chạy bù thì tính as-of tại scheduled_for."""
    need = next(iter(bundle.metas.values()))["required_history_hours"]
    first = t - (need + 24) * HOUR
    if kind == "catchup":
        aggs = await hourly.hourly_as_of(session, node.id, first, t, cutoff=effective_now)
        return [
            HourRow(a.hour_end, a.aqi, a.pm25_avg, a.pm10_avg, a.temperature_avg, a.humidity_avg, None, a.n_samples,
                    a.coverage)
            for a in aggs
        ]  # fmt: skip
    rows = await hourly.series_hour(session, node.id, first - HOUR, t)
    return [
        HourRow(r.hour_end, r.aqi, r.pm25_avg, r.pm10_avg, r.temperature_avg, r.humidity_avg, r.revision, r.n_samples,
                r.coverage)
        for r in rows
    ]  # fmt: skip


def _compute(claim: Claim) -> Outcome:
    """Chạy model (trong thread). Thiếu lịch sử → insufficient_history kèm missing/eta; không có dòng nào → no_data."""
    if not claim.rows:
        return Outcome("no_data", reason="Không có dữ liệu giờ trong cửa sổ đầu vào")
    meta = next(iter(claim.bundle.metas.values()))
    frame = history_frame(claim.rows, claim.t)
    try:
        preds, cache = adapter.predict(claim.bundle, frame, local_naive(claim.t), local_naive(claim.effective_now))
    except adapter.InferenceDataError as exc:
        missing, eta = readiness(claim.rows, claim.t, meta["required_history_hours"], meta["nan_policy"]["name"])
        return Outcome("insufficient_history", reason=str(exc)[:500], missing_hours=missing, eta_hours=eta)
    row = next(iter(cache.values()))
    aqi_t = row["AQI"].iloc[0]
    return Outcome(
        "ok",
        preds=preds,
        features=[float(v) for v in row[meta["feature_columns"]].iloc[0].tolist()],
        persistence=None if aqi_t is None or math.isnan(aqi_t) else int(aqi_t),  # cột AQI tại t sau nan_policy (R34)
    )


async def _finish(session: AsyncSession, claim: Claim, outcome: Outcome, duration_ms: int) -> str:
    """Ghi kết quả nếu lần thử vẫn là lần thử hiện hành; lỗi thì hẹn thử lại 2^n phút (tối đa forecast_max_attempts)."""
    run = await repository.get_run(session, claim.run_id, for_update=True)
    attempt = await repository.get_attempt(session, claim.attempt_id)
    if run is None or attempt is None or run.attempt_count != claim.attempt_no or run.status != "running":
        return "busy"  # lần thử đã bị thay (bị coi là treo) — không ghi đè
    now = claim.started_at + timedelta(milliseconds=duration_ms)  # lúc ghi xong (issued_at)
    attempt.finished_at, attempt.status, attempt.reason = now, outcome.status, outcome.reason
    run.status, run.reason, run.duration_ms = outcome.status, outcome.reason, duration_ms
    run.missing_hours, run.eta_hours = outcome.missing_hours, outcome.eta_hours
    t_row = next((r for r in claim.rows if r.hour_end == claim.t), None)
    run.input_t_samples = t_row.n_samples if t_row else 0
    run.input_t_coverage = t_row.coverage if t_row else None
    run.input_t_revision = t_row.revision if t_row else None
    status = outcome.status
    if outcome.status == "ok":
        run.issued_at = now
        await _store(session, claim, outcome, now)
    elif outcome.status == "error":
        max_attempts = await settings_store.get("forecast_max_attempts")
        if run.attempt_count >= max_attempts:
            status = "error_final"
        else:
            run.next_attempt_at = now + timedelta(minutes=2**run.attempt_count)
    await events.notify(
        session, "forecast_run", {"run_id": run.id, "status": run.status, "issue_kind": run.issue_kind,
                                  "input_hour": claim.t.isoformat()},
        node_id=claim.node.id, station_code=claim.node.station_code,
    )  # fmt: skip
    if outcome.status == "ok" and run.issue_kind in PUBLISHED_KINDS:
        data = {"input_hour": claim.t.isoformat(), "issued_at": now.isoformat(), "status": "ok"}
        await events.notify(session, "forecast", data, node_id=claim.node.id, station_code=claim.node.station_code)
    return status


async def _store(session: AsyncSession, claim: Claim, outcome: Outcome, issued_at: datetime) -> None:
    """Ghi 24 mốc `forecasts`, `forecast_inputs` (184 feature, giữ lâu dài) và `forecast_input_history` (90 ngày)."""
    meta = next(iter(claim.bundle.metas.values()))
    records = history_records(claim.rows)
    forecasts = [
        {"run_id": claim.run_id, "horizon_h": h, "node_id": claim.node.id, "input_hour": claim.t,
         "target_hour": claim.t + h * HOUR, "predicted_aqi": p, "persistence_aqi": outcome.persistence}
        for h, p in sorted(outcome.preds.items())
    ]  # fmt: skip
    features = {
        "run_id": claim.run_id, "issued_at": issued_at, "model_id": claim.bundle.model_id,
        "feature_columns_sha256": sha256_json(meta["feature_columns"]), "features": outcome.features,
        "history_sha256": sha256_json(records),
    }  # fmt: skip
    history = {"run_id": claim.run_id, "issued_at": issued_at, "history": records}
    await repository.insert_results(session, forecasts, features, history)
