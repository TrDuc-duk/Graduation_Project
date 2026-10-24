"""Job nền của module hourly (backend_design 10)."""

from app.core import timeutil
from app.modules.hourly import service


async def hourly_rollup() -> dict:
    """Mỗi 5 phút: tính giờ đang mở (chỉ để hiển thị) rồi tính lại các giờ đã đóng trong hàng đợi.

    Việc đóng giờ không làm ở đây mà ở đường ống giờ (backend_design 7.1).
    """
    now = timeutil.now()
    rolled = await service.rollup_open_hours(now)
    return {**rolled, **await service.process_recompute_queue(now)}
