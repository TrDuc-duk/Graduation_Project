"""Kết nối DB, session và transaction có thử lại (database_design 12, backend_design 6.5)."""

from collections.abc import Awaitable, Callable
from functools import lru_cache

from sqlalchemy import MetaData, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    wait_random,
)

from app.core.config import get_settings

# Lỗi DB nên thử lại: deadlock, serialization, hết thời gian chờ khóa
RETRYABLE_SQLSTATES = {"40P01", "40001", "55P03"}

NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "ux_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}


class Base(DeclarativeBase):
    """Lớp cha của mọi model SQLAlchemy. Schema thật do migration tạo (database_design 11)."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


@lru_cache
def get_engine() -> AsyncEngine:
    """Tạo engine một lần cho cả tiến trình: pool 10 + 5, giờ UTC, statement_timeout mặc định 15 giây."""
    settings = get_settings()
    options = f"-c timezone=UTC -c application_name=aqi-{settings.app_role} -c statement_timeout=15s"
    return create_async_engine(
        settings.database_url,
        pool_size=10,
        max_overflow=5,
        pool_pre_ping=True,
        connect_args={"options": options},
    )


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Nhà máy tạo session; expire_on_commit=False để vẫn đọc được object sau khi commit."""
    return async_sessionmaker(get_engine(), expire_on_commit=False)


def is_retryable(exc: BaseException) -> bool:
    """True nếu lỗi DB thuộc loại thử lại được (deadlock, serialization, lock timeout)."""
    return isinstance(exc, DBAPIError) and getattr(exc.orig, "sqlstate", None) in RETRYABLE_SQLSTATES


async def run_in_transaction[T](
    fn: Callable[[AsyncSession], Awaitable[T]],
    *,
    retries: int = 3,
    lock_timeout: str | None = None,
    statement_timeout: str | None = None,
) -> T:
    """Chạy fn(session) trong một transaction; commit khi xong, rollback khi lỗi.

    Gặp deadlock/serialization/lock timeout thì chạy lại cả transaction, tối đa `retries` lần,
    nghỉ ngẫu nhiên 50–200 ms, tổng thời gian dưới 8 giây (firmware chờ 10 giây).
    fn phải chạy lại được từ đầu (không giữ trạng thái giữa các lần thử).
    """
    retrying = AsyncRetrying(
        retry=retry_if_exception(is_retryable),
        stop=stop_after_attempt(retries + 1) | stop_after_delay(8),
        wait=wait_random(0.05, 0.2),
        reraise=True,
    )
    async for attempt in retrying:
        with attempt:
            async with get_sessionmaker()() as session, session.begin():
                if lock_timeout:
                    await session.execute(text(f"SET LOCAL lock_timeout = '{lock_timeout}'"))
                if statement_timeout:
                    await session.execute(text(f"SET LOCAL statement_timeout = '{statement_timeout}'"))
                return await fn(session)
    raise AssertionError("unreachable")  # AsyncRetrying luôn trả về hoặc ném lỗi
