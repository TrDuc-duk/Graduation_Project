"""Job nền chạy bằng APScheduler (backend_design 10).

Mỗi lần chạy job: giữ khóa job (không chạy chồng giữa các tiến trình), ghi `job_runs` ok/error/skipped.
"""

import json
import logging
import os
import socket
from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text

from app.core.db import run_in_transaction
from app.core.locks import job_lock

log = logging.getLogger(__name__)

JobFn = Callable[[], Awaitable[dict | None]]

PROCESS_ID = f"{socket.gethostname()}:{os.getpid()}"

scheduler = AsyncIOScheduler(timezone="Asia/Ho_Chi_Minh")


def add_job(name: str, fn: JobFn, *, log_runs: bool = True, **trigger: object) -> None:
    """Đăng ký job theo lịch, ví dụ add_job("interval_stats", fn, trigger="interval", hours=1).

    log_runs=False cho job chạy dày (outbox mỗi 5 giây) để không lấp đầy job_runs; lỗi vẫn được ghi.
    """
    scheduler.add_job(run_job, args=[name, fn, log_runs], id=name, max_instances=1, coalesce=True, **trigger)


async def run_job(name: str, fn: JobFn, log_runs: bool = True) -> str:
    """Chạy một lần job có khóa; trả trạng thái 'ok' | 'error' | 'skipped'."""
    async with job_lock(name) as got:
        if not got:
            if log_runs:
                await _log_run(name, "skipped")
            return "skipped"
        try:
            stats = await fn()
        except Exception as exc:  # noqa: BLE001 — job lỗi không được làm chết scheduler
            log.exception("Job %s lỗi", name)
            await _log_run(name, "error", error=repr(exc))
            return "error"
        if log_runs:
            await _log_run(name, "ok", stats=stats)
        return "ok"


async def _log_run(name: str, status: str, stats: dict | None = None, error: str | None = None) -> None:
    """Ghi một dòng job_runs đã kết thúc."""
    await run_in_transaction(
        lambda s: s.execute(
            text(
                "INSERT INTO job_runs (job, process_id, finished_at, status, stats, error) "
                "VALUES (:job, :pid, now(), :status, CAST(:stats AS jsonb), :error)"
            ),
            {
                "job": name,
                "pid": PROCESS_ID,
                "status": status,
                "stats": json.dumps(stats) if stats else None,
                "error": error,
            },
        )
    )
