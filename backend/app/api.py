"""Gắn router của các module vào ứng dụng."""

from fastapi import FastAPI

from app.core.config import get_settings
from app.modules.assistant.router import router as assistant_router
from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.dev.router import router as dev_router
from app.modules.ingest.router import router as device_router
from app.modules.realtime.router import router as stream_router
from app.modules.stations.router import router as public_router
from app.modules.system.router import router as system_router

API_PREFIX = "/api/v1"


def include_routers(app: FastAPI) -> None:
    """Router hệ thống ở gốc; router nghiệp vụ dưới /api/v1.

    API dev chỉ gắn khi ENABLE_DEV_ENDPOINTS=true; API trợ lý chỉ gắn khi đã đặt ASSISTANT_TOKEN.
    """
    settings = get_settings()
    app.include_router(system_router)
    app.include_router(device_router, prefix=API_PREFIX)
    app.include_router(public_router, prefix=API_PREFIX)
    app.include_router(stream_router, prefix=API_PREFIX)
    app.include_router(auth_router, prefix=API_PREFIX)
    app.include_router(audit_router, prefix=API_PREFIX)
    if settings.enable_dev_endpoints:
        app.include_router(dev_router, prefix=API_PREFIX)
    if settings.assistant_token:
        app.include_router(assistant_router, prefix=API_PREFIX)
