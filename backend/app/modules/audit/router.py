"""Admin xem nhật ký thao tác `/api/v1/admin/audit-logs` (backend_design 11.8). Mọi tài khoản đã đăng nhập được xem."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.db import run_in_transaction
from app.core.timeutil import iso_local
from app.modules.audit import service
from app.modules.auth.deps import CurrentActor

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/audit-logs")
async def audit_logs(
    _: CurrentActor,
    user_id: int | None = None,
    entity_type: Annotated[str | None, Query(max_length=50)] = None,
    entity_id: Annotated[str | None, Query(max_length=100)] = None,
    action: Annotated[str | None, Query(max_length=100)] = None,
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict:
    """Nhật ký mới trước, lọc theo người, đối tượng, hành động, khoảng thời gian; phân trang (≤ 200 dòng/trang)."""
    items, total = await run_in_transaction(
        lambda s: service.search(
            s, user_id=user_id, entity_type=entity_type, entity_id=entity_id, action=action, start=from_, end=to,
            page=page, page_size=page_size,
        )
    )  # fmt: skip
    return {
        "items": [
            {"id": x.id, "occurred_at": iso_local(x.occurred_at), "user_id": x.user_id, "username": x.username,
             "action": x.action, "entity_type": x.entity_type, "entity_id": x.entity_id, "changes": x.changes,
             "ip": str(x.ip) if x.ip else None}
            for x in items
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
    }  # fmt: skip
