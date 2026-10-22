"""Lỗi nghiệp vụ và cách trả về client (backend_design 11.1)."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Lỗi của API thường. Trả {"error": {"code", "message", "details"}}."""

    def __init__(self, code: str, http_status: int, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.message = message
        self.details = details or {}


class DeviceError(Exception):
    """Lỗi ở cổng thiết bị. Giữ dạng firmware đã quen: {"success": false, "error": "..."}."""

    def __init__(self, http_status: int, message: str):
        super().__init__(message)
        self.http_status = http_status
        self.message = message


def device_error_response(http_status: int, message: str) -> JSONResponse:
    """Tạo response lỗi theo dạng firmware."""
    return JSONResponse({"success": False, "error": message}, status_code=http_status)


def register_error_handlers(app: FastAPI) -> None:
    """Gắn handler để mọi AppError/DeviceError ra đúng định dạng JSON."""

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        body = {"error": {"code": exc.code, "message": exc.message, "details": exc.details}}
        return JSONResponse(body, status_code=exc.http_status)

    @app.exception_handler(DeviceError)
    async def _device_error(_: Request, exc: DeviceError) -> JSONResponse:
        return device_error_response(exc.http_status, exc.message)
