"""Job nền của module pipeline (backend_design 10)."""

from app.core import timeutil
from app.modules.pipeline import service


async def hourly_pipeline() -> dict:
    """Mỗi phút và ngay khi khởi động: chạy một lượt đường ống giờ."""
    return await service.run(timeutil.now())
