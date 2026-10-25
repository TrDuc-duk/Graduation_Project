"""Truy vấn SQL của module auth. Không commit."""

import uuid
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.models import AuthSession, RefreshToken, User


async def user_by_username(session: AsyncSession, username: str, *, for_update: bool = False) -> User | None:
    """Người dùng theo tên đăng nhập (chữ thường)."""
    stmt = select(User).where(User.username == username.strip().lower())
    return (await session.scalars(stmt.with_for_update() if for_update else stmt)).one_or_none()


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id, populate_existing=True)


async def recent_failures(session: AsyncSession, user_id: int, since: datetime) -> int:
    """Số lần đăng nhập sai của người dùng từ `since` (đếm trong security_events, nguồn đúng theo thời gian)."""
    return int(
        await session.scalar(
            text(
                "SELECT count(*) FROM security_events WHERE kind = 'admin_login_failed' "
                "AND details->>'user_id' = :u AND occurred_at >= :since"
            ),
            {"u": str(user_id), "since": since},
        )
        or 0
    )


async def session_with_user(session: AsyncSession, sid: uuid.UUID) -> tuple[AuthSession, User] | None:
    """Phiên và người dùng của nó (một truy vấn khóa chính, R20)."""
    row = (
        await session.execute(
            select(AuthSession, User).join(User, User.id == AuthSession.user_id).where(AuthSession.id == sid)
        )
    ).first()
    return None if row is None else (row[0], row[1])


async def lock_session(session: AsyncSession, sid: uuid.UUID) -> AuthSession | None:
    """Khóa dòng phiên (mọi refresh và thu hồi đều khóa phiên trước, R20)."""
    stmt = select(AuthSession).where(AuthSession.id == sid).with_for_update().execution_options(populate_existing=True)
    return (await session.scalars(stmt)).one_or_none()


async def lock_user_sessions(session: AsyncSession, user_id: int) -> list[AuthSession]:
    """Khóa các phiên còn hiệu lực của người dùng theo thứ tự sid (tránh deadlock khi thu hồi nhiều phiên)."""
    stmt = (
        select(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .order_by(AuthSession.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return list((await session.scalars(stmt)).all())


async def token_by_hash(session: AsyncSession, token_hash: bytes) -> RefreshToken | None:
    return (await session.scalars(select(RefreshToken).where(RefreshToken.token_hash == token_hash))).one_or_none()


async def lock_token(session: AsyncSession, token_id: int) -> RefreshToken | None:
    stmt = (
        select(RefreshToken)
        .where(RefreshToken.id == token_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return (await session.scalars(stmt)).one_or_none()


async def get_token(session: AsyncSession, token_id: int) -> RefreshToken | None:
    return await session.get(RefreshToken, token_id, populate_existing=True)


async def active_sessions(session: AsyncSession, user_id: int, now: datetime) -> list[AuthSession]:
    """Phiên chưa thu hồi, chưa hết hạn của người dùng, mới dùng trước."""
    stmt = (
        select(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None), AuthSession.expires_at > now)
        .order_by(AuthSession.last_seen_at.desc())
    )
    return list((await session.scalars(stmt)).all())


async def count_users(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(User)) or 0)
