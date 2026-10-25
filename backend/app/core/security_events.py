"""Ghi sự kiện bảo mật (backend_design 14.3) để Admin xem ở trang Hệ thống."""

import json
from datetime import datetime
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import run_in_transaction

Severity = Literal["info", "warning", "critical"]


async def record(
    session: AsyncSession,
    kind: str,
    severity: Severity,
    *,
    source_ip: str | None = None,
    gateway_id: str | None = None,
    node_id: int | None = None,
    occurred_at: datetime | None = None,
    **details: object,
) -> None:
    """Ghi một sự kiện trong transaction hiện tại. `details` là thông tin thêm, không chứa secret.

    `occurred_at` mặc định là giờ DB; truyền thời điểm của ứng dụng khi cần đếm theo cửa sổ (vd đăng nhập sai).
    """
    await session.execute(
        text(
            "INSERT INTO security_events (occurred_at, kind, severity, source_ip, gateway_id, node_id, details) "
            "VALUES (coalesce(:at, now()), :kind, :sev, CAST(:ip AS inet), :gw, :node, CAST(:details AS jsonb))"
        ),
        {
            "at": occurred_at,
            "kind": kind,
            "sev": severity,
            "ip": source_ip,
            "gw": gateway_id,
            "node": node_id,
            "details": json.dumps(details, default=str) if details else None,
        },
    )


async def record_now(kind: str, severity: Severity, **kwargs: object) -> None:
    """Ghi sự kiện trong một transaction riêng (khi request đang bị từ chối, không có transaction nào)."""
    await run_in_transaction(lambda s: record(s, kind, severity, **kwargs))
