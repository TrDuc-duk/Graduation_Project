"""API dev chỉ đọc cho dashboard demo. Chỉ được gắn khi ENABLE_DEV_ENDPOINTS=true (xem app/api.py).

Khác API công khai sau này (M2): trả cả node pending và số đo đang cách ly, kèm cờ để giao diện ghi rõ.
"""

from fastapi import APIRouter

from app.core.db import run_in_transaction
from app.core.errors import AppError
from app.modules.dev import service
from app.modules.dev.schemas import NodeOut, NodeReadings

router = APIRouter(prefix="/dev", tags=["dev"])

ALLOWED_HOURS = (1, 6, 24, 168, 720)  # 168, 720 giờ (7, 30 ngày) trả trung bình theo giờ


@router.get("/nodes")
async def list_nodes() -> list[NodeOut]:
    """Danh sách node (kể cả pending) kèm Gateway gần nhất và độ mới dữ liệu."""
    return await run_in_transaction(service.list_nodes)


@router.get("/nodes/{node_id}/readings")
async def node_readings(node_id: int, hours: int = 1) -> NodeReadings:
    """Số đo của node trong 1, 6, 24 giờ (thô) hoặc 168, 720 giờ (trung bình giờ) gần nhất, kèm số đo mới nhất."""
    if hours not in ALLOWED_HOURS:
        raise AppError("INVALID_RANGE", 422, "hours chỉ nhận 1, 6, 24, 168 hoặc 720")
    result = await run_in_transaction(lambda s: service.node_readings(s, node_id, hours))
    if result is None:
        raise AppError("NODE_NOT_FOUND", 404, "Không tìm thấy node")
    return result
