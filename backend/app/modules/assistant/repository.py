"""SQL của module assistant: ghi nhật ký lệnh gọi (bảng assistant_calls). Không commit."""

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def log_call(
    session: AsyncSession,
    *,
    tool: str,
    params: dict,
    station_code: str | None,
    node_id: int | None,
    status: str,
    error_code: str | None,
    duration_ms: int,
) -> None:
    """Thêm một dòng nhật ký: tên tool, tham số, trạm, kết quả (ok/error + mã lỗi), thời gian xử lý."""
    await session.execute(
        text(
            "INSERT INTO assistant_calls (tool, params, station_code, node_id, status, error_code, duration_ms) "
            "VALUES (:tool, CAST(:params AS jsonb), :station_code, :node_id, :status, :error_code, :duration_ms)"
        ),
        {
            "tool": tool,
            "params": json.dumps(params, ensure_ascii=False),
            "station_code": station_code,
            "node_id": node_id,
            "status": status,
            "error_code": error_code,
            "duration_ms": duration_ms,
        },
    )
