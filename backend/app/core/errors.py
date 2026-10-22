"""Lỗi nghiệp vụ và cách trả về client (backend_design 11.1)."""

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
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


class AssistantError(Exception):
    """Lỗi của API trợ lý. Trả {"ok": false, "code", "message_vi", ...} để chatbot đọc được (09-xiaozhi-mcp §5)."""

    def __init__(self, code: str, http_status: int, message_vi: str, **extra: object):
        super().__init__(message_vi)
        self.code = code
        self.http_status = http_status
        self.message_vi = message_vi
        self.extra = extra  # thông tin thêm, vd danh sách trạm để chatbot hỏi lại


def device_error_response(http_status: int, message: str) -> JSONResponse:
    """Tạo response lỗi theo dạng firmware."""
    return JSONResponse({"success": False, "error": message}, status_code=http_status)


def register_error_handlers(app: FastAPI) -> None:
    """Gắn handler để mọi AppError/DeviceError/AssistantError ra đúng định dạng JSON."""

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        body = {"error": {"code": exc.code, "message": exc.message, "details": exc.details}}
        return JSONResponse(body, status_code=exc.http_status)

    @app.exception_handler(DeviceError)
    async def _device_error(_: Request, exc: DeviceError) -> JSONResponse:
        return device_error_response(exc.http_status, exc.message)

    @app.exception_handler(AssistantError)
    async def _assistant_error(_: Request, exc: AssistantError) -> JSONResponse:
        body = {"ok": False, "code": exc.code, "message_vi": exc.message_vi, **exc.extra}
        return JSONResponse(jsonable_encoder(body), status_code=exc.http_status)
