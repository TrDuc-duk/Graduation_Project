"""API trợ lý cho xiaozhi-bridge: /api/v1/assistant/* (backend_design 11.9, 09-xiaozhi-mcp).

Chỉ đọc, xác thực bằng `Authorization: Bearer <ASSISTANT_TOKEN>`; chỉ gắn khi đã đặt token (app/api.py).
Reverse proxy không định tuyến nhóm này ra Internet. Mỗi lần gọi ghi một dòng assistant_calls và một dòng log.
"""

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import run_in_transaction
from app.core.errors import AssistantError
from app.core.security import matches_any
from app.modules.assistant import repository, service
from app.modules.assistant.schemas import CurrentOut, ForecastOut, StationsOut, SummaryOut
from app.modules.assistant.service import CallContext

log = logging.getLogger(__name__)


async def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    """Chỉ cho token trợ lý (quyền assistant:read); so sánh thời gian hằng, không ghi token vào log."""
    token = authorization[7:].strip() if authorization and authorization.startswith("Bearer ") else None
    if not matches_any(token, [get_settings().assistant_token]):
        raise AssistantError("UNAUTHORIZED", 401, "Thiếu hoặc sai token trợ lý.")


router = APIRouter(prefix="/assistant", tags=["assistant"], dependencies=[Depends(require_token)])


async def _call[T](ctx: CallContext, fn: Callable[[AsyncSession], Awaitable[T]]) -> T:
    """Chạy một tool trong transaction chỉ đọc; ghi nhật ký kết quả và thời gian xử lý.

    Lỗi DB đổi thành BACKEND_UNAVAILABLE (503) để chatbot báo không lấy được dữ liệu thay vì đọc lỗi kỹ thuật.
    """
    started = time.perf_counter()
    status, error_code = "ok", None
    try:
        return await run_in_transaction(fn)
    except AssistantError as e:
        status, error_code = "error", e.code
        raise
    except SQLAlchemyError as e:
        status, error_code = "error", "BACKEND_UNAVAILABLE"
        raise AssistantError("BACKEND_UNAVAILABLE", 503, "Hệ thống tạm thời không đọc được dữ liệu.") from e
    finally:
        ms = int((time.perf_counter() - started) * 1000)
        log.info("assistant %s %s %s station=%s %dms", ctx.tool, status, error_code or "-", ctx.station_code, ms)
        try:
            await run_in_transaction(
                lambda s: repository.log_call(
                    s,
                    tool=ctx.tool,
                    params=ctx.params,
                    station_code=ctx.station_code,
                    node_id=ctx.node_id,
                    status=status,
                    error_code=error_code,
                    duration_ms=ms,
                )
            )
        except SQLAlchemyError:
            log.warning("Không ghi được assistant_calls cho %s", ctx.tool)


@router.get("/stations")
async def list_stations() -> StationsOut:
    """Danh sách trạm (mã, tên, khu vực, đang gửi dữ liệu không) và trạm mặc định."""
    ctx = CallContext("list_stations")
    return await _call(ctx, lambda s: service.list_stations(s, ctx))


@router.get("/stations/{ref}/current")
async def current(ref: str) -> CurrentOut:
    """AQI tức thời, mức AQI, PM2.5, PM10, nhiệt độ, độ ẩm hiện tại của trạm (`ref` = mã, tên hoặc "default")."""
    ctx = CallContext("get_current_air_quality", {"station": ref})
    return await _call(ctx, lambda s: service.current(s, ref, ctx))


@router.get("/stations/{ref}/summary")
async def summary(ref: str, hours: str | None = None) -> SummaryOut:
    """Trung bình, thấp nhất, cao nhất, xu hướng trong `hours` giờ gần nhất (1–72, mặc định 24)."""
    ctx = CallContext("get_history_summary", {"station": ref, "hours": hours})
    return await _call(ctx, lambda s: service.history_summary(s, ref, hours, ctx))


@router.get("/stations/{ref}/forecast")
async def forecast(ref: str, horizons: str | None = None) -> ForecastOut:
    """Dự báo đã lưu theo các mốc `horizons` (vd "3,6,12,24"); chưa có dự báo thì trả trạng thái và lý do."""
    ctx = CallContext("get_forecast", {"station": ref, "horizons": horizons})
    return await _call(ctx, lambda s: service.forecast(s, ref, horizons, ctx))
