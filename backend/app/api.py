"""Gắn router của các module vào ứng dụng."""

from fastapi import FastAPI

from app.core.config import get_settings
from app.modules.dev.router import router as dev_router
from app.modules.ingest.router import router as device_router
from app.modules.system.router import router as system_router

API_PREFIX = "/api/v1"


def include_routers(app: FastAPI) -> None:
    """Router hệ thống ở gốc; router nghiệp vụ dưới /api/v1. API dev chỉ gắn khi ENABLE_DEV_ENDPOINTS=true."""
    app.include_router(system_router)
    app.include_router(device_router, prefix=API_PREFIX)
    if get_settings().enable_dev_endpoints:
        app.include_router(dev_router, prefix=API_PREFIX)
