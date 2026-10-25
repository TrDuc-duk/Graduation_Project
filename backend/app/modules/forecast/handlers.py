"""Handler outbox của module forecast (backend_design 6.9, 8.5)."""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import outbox, timeutil
from app.modules.forecast import evaluate


async def on_hourly_revised(session: AsyncSession, payload: dict) -> None:
    """`hourly_revised {node_id, hour_end, revision}`: đánh giá lại dự báo có giờ đích đó (chỉ khi revision mới hơn)
    và tính lại độ chính xác ngày. Idempotent: chạy lại cùng sự kiện không đổi gì thêm."""
    hour_end = datetime.fromisoformat(payload["hour_end"])
    await evaluate.apply_revision(session, int(payload["node_id"]), hour_end, int(payload["revision"]), timeutil.now())


def register() -> None:
    """Đăng ký handler (gọi một lần khi khởi tạo ứng dụng, trước khi dispatcher chạy)."""
    outbox.register_handler("hourly_revised", on_hourly_revised)
