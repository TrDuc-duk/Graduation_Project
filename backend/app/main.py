"""Điểm vào FastAPI: `uvicorn app.main:app`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import include_routers
from app.core import outbox
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.errors import register_error_handlers
from app.core.logging import setup_logging
from app.core.scheduler import add_job, scheduler
from app.modules.hourly.jobs import hourly_rollup
from app.modules.ingest.jobs import interval_stats
from app.modules.pipeline.jobs import hourly_pipeline
from app.modules.weather import service as weather


def register_jobs() -> None:
    """Khai báo mọi job nền (backend_design 10). Chỉ gọi khi tiến trình được phép chạy job."""
    add_job("outbox_dispatcher", outbox.dispatch_once, log_runs=False, trigger="interval", seconds=5)
    add_job("interval_stats", interval_stats, trigger="interval", hours=1)
    add_job("hourly_rollup", hourly_rollup, trigger="interval", minutes=5)
    # Đường ống giờ: mỗi phút và chạy ngay khi khởi động (bù giờ còn thiếu sau restart, backend_design 7.1)
    add_job("hourly_pipeline", hourly_pipeline, trigger="interval", minutes=1, next_run_time=datetime.now(UTC))


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Khởi động: log, job nền (vai trò all/worker). Tắt: dừng job, đóng pool DB."""
    settings = get_settings()
    setup_logging(settings.log_level)
    if settings.scheduler_active:
        register_jobs()
        scheduler.start()
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)
    await weather.close()
    await get_engine().dispose()


def create_app() -> FastAPI:
    """Tạo ứng dụng; tài liệu OpenAPI chỉ bật khi ENABLE_API_DOCS=true."""
    docs = get_settings().enable_api_docs
    app = FastAPI(
        title="AQI backend",
        lifespan=lifespan,
        docs_url="/api/docs" if docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs else None,
    )
    register_error_handlers(app)
    if get_settings().cors_origins:  # production cùng origin qua proxy nên không bật (backend_design 14.4)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=get_settings().cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    include_routers(app)
    return app


app = create_app()
