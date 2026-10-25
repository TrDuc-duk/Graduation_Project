"""Giao diện của module audit: ghi nhật ký thao tác (cùng transaction với nghiệp vụ) và tra cứu.

Ghi trong transaction của thao tác: nghiệp vụ rollback thì nhật ký cũng không còn (không có "thành công giả").
Mật khẩu, token, secret, khóa provisioning, hash không bao giờ vào `changes` (thay bằng "***").
"""

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit import repository
from app.modules.audit.models import AuditLog

REDACTED = "***"
_SENSITIVE = ("password", "token", "secret", "provision_key", "hash", "jwt", "cookie", "api_key")


def redact(value: object) -> object:
    """Che mọi khóa có tên nhạy cảm (đệ quy trong dict/list)."""
    if isinstance(value, dict):
        return {k: REDACTED if any(s in str(k).lower() for s in _SENSITIVE) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


async def record(
    session: AsyncSession,
    action: str,
    *,
    user_id: int | None = None,
    username: str | None = None,
    entity_type: str | None = None,
    entity_id: str | int | None = None,
    changes: dict | None = None,
    ip: str | None = None,
) -> None:
    """Ghi một thao tác, ví dụ record(s, "node.approve", user_id=1, username="admin", entity_type="node", …)."""
    await repository.insert_log(
        session,
        user_id=user_id,
        username=username,
        action=action,
        entity_type=entity_type,
        entity_id=None if entity_id is None else str(entity_id),
        changes=redact(changes) if changes else None,
        ip=ip,
    )


async def search(
    session: AsyncSession,
    *,
    user_id: int | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    action: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[AuditLog], int]:
    """Tra nhật ký mới trước, có lọc và phân trang (page từ 1, page_size ≤ 200)."""
    filters = {"user_id": user_id, "entity_type": entity_type, "entity_id": entity_id, "action": action}
    return await repository.search(session, filters, start, end, (page - 1) * page_size, page_size)
