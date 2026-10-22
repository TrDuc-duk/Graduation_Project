"""Khóa advisory dạng hai số (lớp, khóa) (database_design 8.3).

Lớp 1: job (khóa phiên); lớp 2: địa chỉ node `mạng × 256 + địa chỉ` (khóa transaction); lớp 3: đường ống giờ.
"""

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_engine

JOB_CLASS = 1
NODE_ADDRESS_CLASS = 2

# Mã job (database_design 8.4)
JOB_CODES = {
    "hourly_pipeline": 1,
    "hourly_rollup": 2,
    "outbox_dispatcher": 3,
    "device_status": 4,
    "interval_stats": 5,
    "notify_retry": 6,
    "cleanup": 7,
    "rate_counters_gc": 8,
}


def address_key(lora_network_id: int, lora_addr: int) -> int:
    """Khóa của một địa chỉ node: mạng × 256 + địa chỉ (địa chỉ 1–255, nên 0 còn trống)."""
    return lora_network_id * 256 + lora_addr


async def node_address_locks(session: AsyncSession, keys: Iterable[int]) -> None:
    """Khóa các địa chỉ node đến hết transaction, theo thứ tự tăng dần để không deadlock (R10)."""
    for key in sorted(set(keys)):
        await session.execute(text("SELECT pg_advisory_xact_lock(:c, :k)"), {"c": NODE_ADDRESS_CLASS, "k": key})


@asynccontextmanager
async def job_lock(job: str) -> AsyncIterator[bool]:
    """Thử giữ khóa job trên một kết nối riêng; trả True nếu lấy được, False nếu job khác đang chạy.

    Khóa phiên không tự nhả khi transaction kết thúc, nên luôn nhả trong finally (backend_design 10).
    """
    code = JOB_CODES[job]
    async with get_engine().connect() as conn:
        got = await conn.scalar(text("SELECT pg_try_advisory_lock(:c, :k)"), {"c": JOB_CLASS, "k": code})
        await conn.commit()
        try:
            yield bool(got)
        finally:
            if got:
                await conn.execute(text("SELECT pg_advisory_unlock(:c, :k)"), {"c": JOB_CLASS, "k": code})
                await conn.commit()
