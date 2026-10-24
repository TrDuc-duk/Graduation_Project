"""Đường ống theo giờ (backend_design 7.1): với mỗi nhãn giờ, chạy các bước theo thứ tự, lưu tiến độ trong DB.

Cron chỉ là bộ kích hoạt: mỗi lượt đi từ giờ chưa xong cũ nhất tới giờ đóng được mới nhất, không bỏ giờ nào,
nên chạy trễ, chạy lại hay chạy bù sau restart đều cho cùng kết quả (R1, R2).
M2 chỉ có bước 1 (đóng giờ). Bước 2, 5 (cảnh báo, M5) để trống; bước 3, 4 (dự báo) thêm ở M3.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings_store
from app.core.db import run_in_transaction
from app.core.locks import pipeline_lock
from app.core.timeutil import floor_hour
from app.modules.hourly import service as hourly
from app.modules.pipeline import repository
from app.modules.pipeline.models import HourPipeline

log = logging.getLogger(__name__)

HOUR = timedelta(hours=1)
RETENTION = timedelta(days=90)  # dữ liệu thô giữ 90 ngày: giờ cũ hơn không còn gì để đóng (P8)
MAX_HOURS_PER_RUN = 48  # mỗi lượt xử lý hữu hạn giờ để không giữ khóa quá lâu; lượt sau làm tiếp

Step = Callable[[datetime, datetime], Awaitable[object]]


async def _close(hour_end: datetime, now: datetime) -> object:
    """Bước 1: đóng giờ (tính node_hourly cho mọi node có dữ liệu)."""
    return await hourly.close_hour(hour_end, now)


# (cột ghi thời điểm xong, hàm chạy bước) theo đúng thứ tự; giờ "xong" khi mọi cột khác NULL
STEPS: list[tuple[str, Step]] = [("closed_at", _close)]


def done_columns() -> tuple[str, ...]:
    """Các cột tiến độ quyết định một giờ đã xong ở mốc hiện tại (M2: chỉ `closed_at`)."""
    return tuple(column for column, _ in STEPS)


async def latest_closable_hour(now: datetime) -> datetime:
    """Giờ `h` mới nhất đã qua mốc đóng: now ≥ h + hour_close_grace_s."""
    grace = await settings_store.get("hour_close_grace_s")
    return floor_hour(now - timedelta(seconds=grace))


async def run(now: datetime) -> dict:
    """Một lượt đường ống, giữ khóa (3, 0). Dừng ở giờ đầu tiên có bước lỗi (giờ sau phải chờ, giữ thứ tự)."""
    async with pipeline_lock() as got:
        if not got:
            return {"skipped": True}
        latest = await latest_closable_hour(now)
        since = floor_hour(now - RETENTION)
        await run_in_transaction(lambda s: _add_new_hours(s, latest, since))
        rows = await run_in_transaction(
            lambda s: repository.unfinished(s, done_columns(), since, latest, MAX_HOURS_PER_RUN)
        )
        done = 0
        for row in rows:
            if not await _run_hour(row, now):
                return {"done": done, "failed_hour": row.hour_end.isoformat()}
            done += 1
        return {"done": done}


async def progress(session: AsyncSession, limit: int = 50) -> dict:
    """Tiến độ cho trang Hệ thống: giờ mới nhất đã có, các giờ chưa xong hoặc đang lỗi (mới trước)."""
    rows = await repository.progress_rows(session, done_columns(), limit)
    return {
        "latest_hour": await repository.latest_hour(session),
        "steps": list(done_columns()),
        "pending": [
            {
                "hour_end": r.hour_end,
                "closed_at": r.closed_at,
                "eval_done_at": r.eval_done_at,
                "forecast_done_at": r.forecast_done_at,
                "attempts": r.attempts,
                "last_error": r.last_error,
            }
            for r in rows
        ],
    }


async def _add_new_hours(session: AsyncSession, latest: datetime, since: datetime) -> None:
    """Thêm dòng tiến độ cho các giờ mới tới `latest`. DB trống thì chỉ bắt đầu từ giờ đóng được mới nhất."""
    last = await repository.latest_hour(session)
    if last is None:
        hours = [latest]
    else:
        start = max(last + HOUR, since)
        hours = [start + i * HOUR for i in range(int((latest - start) / HOUR) + 1)] if start <= latest else []
    await repository.ensure_hours(session, hours)


async def _run_hour(row: HourPipeline, now: datetime) -> bool:
    """Chạy các bước chưa xong của một giờ theo thứ tự; bước lỗi thì ghi lỗi và trả False."""
    for column, step in STEPS:
        if getattr(row, column) is not None:
            continue
        try:
            await step(row.hour_end, now)
        except Exception as exc:  # noqa: BLE001 — lỗi một bước được ghi lại và thử lại ở lần kích hoạt sau
            log.exception("Đường ống giờ %s lỗi ở bước %s", row.hour_end, column)
            error = f"{column}: {exc!r}"
            await run_in_transaction(lambda s, e=error: repository.mark_error(s, row.hour_end, e))
            return False
        await run_in_transaction(lambda s, c=column: repository.mark_step_done(s, row.hour_end, c, now))
    return True
