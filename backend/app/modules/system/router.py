"""Kiểm tra sức khỏe tiến trình (backend_design 11.10). Đặt ở gốc, không có tiền tố /api/v1."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.db import get_sessionmaker

router = APIRouter(tags=["system"])

REQUIRED_EXTENSIONS = ("timescaledb", "postgis")


@router.get("/healthz")
async def healthz() -> dict:
    """Tiến trình còn sống (không kiểm tra DB)."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz() -> JSONResponse:
    """Sẵn sàng nhận request: DB kết nối được và có đủ extension. Chưa có model không tính là lỗi."""
    try:
        async with get_sessionmaker()() as session:
            rows = await session.scalars(text("SELECT extname FROM pg_extension"))
            installed = set(rows.all())
    except Exception:  # noqa: BLE001 — mọi lỗi kết nối đều là "chưa sẵn sàng"
        return JSONResponse({"status": "unavailable", "db": "error"}, status_code=503)

    extensions = {name: name in installed for name in REQUIRED_EXTENSIONS}
    ready = all(extensions.values())
    body = {"status": "ok" if ready else "unavailable", "db": "ok", "extensions": extensions, "model": "not_loaded"}
    return JSONResponse(body, status_code=200 if ready else 503)
