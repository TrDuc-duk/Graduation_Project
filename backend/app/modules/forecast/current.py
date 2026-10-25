"""Dự báo hiện hành của một trạm (backend_design 11.5, R23, R31): dùng chung cho web và trợ lý.

- `latest_success`: lần chạy `ok` mới nhất loại on_time / late / manual (không bao giờ là `catchup`).
- `due_hour`: giờ h mới nhất mà đồng hồ đã qua hạn phát hành h + grace + 120 giây + forecast_late_after_s
  (mặc định h + 15 phút); tính từ `now` nên worker dừng thì tuổi vẫn tăng.
- `age_hours = max(due_hour, latest_success.input_hour) − latest_success.input_hour`: 0 → ok; ≤ 6 → stale (chỉ
  mốc tương lai); không có hoặc quá 6 giờ → trạng thái của lần chạy gần nhất, không có số.
`typical_error` là sai số tham khảo (MAE), không phải khoảng tin cậy (§8.6).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings_store
from app.core.aqi_scale import level_of
from app.core.timeutil import floor_hour, to_local
from app.modules.forecast import repository
from app.modules.forecast.models import ForecastRun
from app.modules.mlruntime import service as mlruntime

HOUR = timedelta(hours=1)
PUBLISHED_KINDS = ("on_time", "late", "manual")
LIVE_MIN_PAIRS = 50  # đủ 50 cặp đối chiếu trong 30 ngày thì dùng MAE thực tế
LIVE_WINDOW_DAYS = 30
NO_NUMBER_STATUSES = ("insufficient_history", "no_data", "error")


@dataclass(frozen=True)
class Item:
    """Một mốc dự báo công khai."""

    horizon_h: int
    target_time: datetime
    aqi: int
    level: str | None
    confidence: str  # high | medium | low
    typical_error: float | None
    error_source: str | None  # live | training


@dataclass(frozen=True)
class Published:
    """Dự báo được hiện: phiên bản model, giờ đầu vào, lúc phát hành, loại phát hành, độ phủ giờ t, các mốc."""

    model_version: str
    input_hour: datetime
    issued_at: datetime
    issue_kind: str
    input_coverage: float | None
    items: list[Item]


@dataclass(frozen=True)
class Attempt:
    """Lần chạy gần nhất (mọi trạng thái); `readiness` chỉ có khi thiếu lịch sử."""

    input_hour: datetime
    status: str
    readiness: dict | None


@dataclass(frozen=True)
class CurrentForecast:
    """Kết quả cho một trạm: trạng thái, độ mới, dự báo (hoặc None), lần chạy gần nhất, khóa thông điệp i18n."""

    status: str  # ok | stale | insufficient_history | no_data | error | unavailable
    age_hours: int | None
    expected_input_hour: datetime
    forecast: Published | None
    latest_attempt: Attempt | None
    message_key: str | None
    message_params: dict


async def current_forecast(
    session: AsyncSession, node_id: int, now: datetime, horizons: list[int] | None = None
) -> CurrentForecast:
    """Dự báo hiện hành của node lúc `now`, lọc theo `horizons` (mặc định `public_horizons`)."""
    settings = await settings_store.get_many(
        "hour_close_grace_s", "forecast_late_after_s", "forecast_stale_max_h", "public_horizons", "forecast_confidence"
    )
    lag = timedelta(seconds=settings["hour_close_grace_s"] + 120 + settings["forecast_late_after_s"])
    due_hour = floor_hour(now - lag)
    success = await repository.latest_success(session, node_id, PUBLISHED_KINDS)
    last = await repository.latest_run(session, node_id)
    attempt = await _attempt(session, last) if last else None
    expected = max(due_hour, success.input_hour) if success else due_hour
    age = int((expected - success.input_hour) / HOUR) if success else None

    if success is not None and age <= settings["forecast_stale_max_h"]:
        wanted = [h for h in settings["public_horizons"] if horizons is None or h in horizons]
        published = await _published(session, success, wanted, now, settings["forecast_confidence"])
        if age == 0:
            return CurrentForecast("ok", 0, expected, published, attempt, None, {})
        key = (
            "forecast.stale_insufficient" if attempt and attempt.status == "insufficient_history" else "forecast.stale"
        )
        return CurrentForecast("stale", age, expected, published, attempt, key, {"age": age})

    status = attempt.status if attempt and attempt.status in NO_NUMBER_STATUSES else "unavailable"
    params = {}
    if status == "insufficient_history" and attempt.readiness:
        params = {"required": attempt.readiness["required_hours"], "eta": attempt.readiness["eta_hours"]}
    return CurrentForecast(status, age, expected, None, attempt, f"forecast.{status}", params)


async def _attempt(session: AsyncSession, run: ForecastRun) -> Attempt:
    """Lần chạy gần nhất; thiếu lịch sử thì kèm readiness (số giờ cần, số giờ thiếu, còn bao lâu)."""
    readiness = None
    if run.status == "insufficient_history":
        info = await mlruntime.model_info(session, run.model_id)
        readiness = {
            "required_hours": info.required_history_hours if info else None,
            "missing_hours": run.missing_hours,
            "eta_hours": run.eta_hours,
        }
    return Attempt(run.input_hour, run.status, readiness)


async def _published(
    session: AsyncSession, run: ForecastRun, horizons: list[int], now: datetime, confidence: dict
) -> Published:
    """Các mốc của lần chạy được hiện: chỉ mốc trong `horizons` và có `target_time > now`."""
    info = await mlruntime.model_info(session, run.model_id)
    live = await repository.live_mae(
        session, run.node_id, run.model_id, (to_local(now) - timedelta(days=LIVE_WINDOW_DAYS)).date(), PUBLISHED_KINDS
    )
    items = []
    for f in await repository.forecasts_of(session, run.id):
        if f.horizon_h not in horizons or f.target_hour <= now:
            continue
        aqi = max(0, min(500, round(f.predicted_aqi)))
        error, source = _typical_error(f.horizon_h, live, info.summary if info else {})
        level = level_of(aqi)
        items.append(
            Item(f.horizon_h, f.target_hour, aqi, level.key if level else None, _confidence(f.horizon_h, confidence),
                 error, source)
        )  # fmt: skip
    return Published(
        model_version=info.model_version if info else "?",
        input_hour=run.input_hour,
        issued_at=run.issued_at,
        issue_kind=run.issue_kind,
        input_coverage=None if run.input_t_coverage is None else round(run.input_t_coverage, 2),
        items=items,
    )


def _confidence(horizon: int, ranges: dict) -> str:
    """Nhãn độ tin cậy theo khoảng horizon trong `forecast_confidence` (3–6 high, 9–24 medium, 27–72 low)."""
    for label in ("high", "medium", "low"):
        low, high = ranges[label]
        if low <= horizon <= high:
            return label
    return "low"


def _typical_error(horizon: int, live: dict[int, tuple[int, float]], summary: dict) -> tuple[float | None, str | None]:
    """MAE thực tế 30 ngày khi có ≥ 50 cặp; chưa đủ thì MAE tập test lúc train trong metadata."""
    n, mae = live.get(horizon, (0, 0.0))
    if n >= LIVE_MIN_PAIRS:
        return round(mae, 1), "live"
    trained = (summary.get(str(horizon)) or {}).get("test_mae")
    return (round(trained, 1), "training") if trained is not None else (None, None)
