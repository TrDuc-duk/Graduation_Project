"""Nghiệp vụ đăng nhập và phiên (backend_design 11.7, P12, R20, R33).

- Access JWT 30 phút mang `sid`; mỗi request Admin tra phiên + người dùng (thu hồi có hiệu lực ngay, vai trò lấy
  từ DB nên đổi vai trò có hiệu lực ở request kế tiếp).
- Refresh token opaque, xoay mỗi lần dùng; token kế tiếp suy được từ token cha (HKDF) nên refresh lặp lại trong
  khoảng ân hạn (`refresh_grace_s`) trả lại đúng cookie kế tiếp; dùng lại token đã xoay quá ân hạn → thu hồi
  **phiên đó** (`reuse_detected`).
- Mọi lần thu hồi ghi `revoked_at` và `pg_notify session_revoked {sid}` cùng transaction (đóng SSE Admin, R32).
- Lỗi được trả về dạng kết quả (không ném lỗi HTTP trong transaction) để việc thu hồi/đếm sai luôn được commit.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events, security, security_events, settings_store
from app.modules.audit import service as audit
from app.modules.auth import repository
from app.modules.auth.models import AuthSession, RefreshToken, User

ACCESS_TTL = timedelta(minutes=30)
SESSION_TTL = timedelta(days=14)  # hạn tuyệt đối của phiên; xoay refresh không kéo dài hạn này
LOCK_AFTER_FAILURES = 5
FAILURE_WINDOW = timedelta(minutes=15)
LOCK_FOR = timedelta(minutes=15)
LAST_SEEN_EVERY = timedelta(minutes=1)
_DUMMY_HASH = security.hash_password("không-phải-mật-khẩu-thật")  # cân thời gian khi tên đăng nhập không tồn tại


@dataclass(frozen=True)
class Tokens:
    """Kết quả đăng nhập/refresh: access token (body) và refresh token (cookie HttpOnly)."""

    access_token: str
    access_expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime
    session_id: uuid.UUID
    user: User


@dataclass(frozen=True)
class Failure:
    """Lỗi xác thực: mã ổn định cho client (INVALID_CREDENTIALS, ACCOUNT_LOCKED, INVALID_REFRESH, SESSION_REVOKED)."""

    code: str
    locked_until: datetime | None = None


class AuthError(Exception):
    """Access token không dùng được: 401 với mã `code` (SESSION_REVOKED cho phiên bị thu hồi/hết hạn)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class KeyMismatchError(Exception):
    """Token kế tiếp tính lại không khớp hash đã lưu: lỗi cấu hình JWT_SECRET phía server (§11.7, R33)."""


# ---------- đăng nhập ----------


async def login(
    session: AsyncSession, username: str, password: str, ip: str | None, user_agent: str | None, now: datetime
) -> Tokens | Failure:
    """Kiểm tra mật khẩu; sai 5 lần trong 15 phút → khóa tạm 15 phút (đếm trong DB, không đếm trong RAM)."""
    user = await repository.user_by_username(session, username, for_update=True)
    if user is None:
        security.verify_password(_DUMMY_HASH, password)  # không để lộ tên đăng nhập có tồn tại qua thời gian
        await security_events.record(
            session, "admin_login_failed", "warning", source_ip=ip, occurred_at=now, username=username[:50]
        )
        return Failure("INVALID_CREDENTIALS")
    if user.locked_until is not None and user.locked_until > now:
        return Failure("ACCOUNT_LOCKED", user.locked_until)
    if not user.is_active or not security.verify_password(user.password_hash, password):
        await security_events.record(
            session,
            "admin_login_failed",
            "warning",
            source_ip=ip,
            occurred_at=now,
            user_id=str(user.id),
            username=user.username,
        )
        user.failed_login_count = await repository.recent_failures(session, user.id, now - FAILURE_WINDOW)
        if user.failed_login_count >= LOCK_AFTER_FAILURES:
            user.locked_until = now + LOCK_FOR
            await security_events.record(session, "admin_locked", "warning", source_ip=ip, user_id=str(user.id))
            await audit.record(
                session,
                "user.locked",
                user_id=user.id,
                username=user.username,
                entity_type="user",
                entity_id=user.id,
                changes={"locked_until": user.locked_until.isoformat()},
                ip=ip,
            )
            return Failure("ACCOUNT_LOCKED", user.locked_until)
        return Failure("INVALID_CREDENTIALS")
    user.failed_login_count, user.locked_until, user.last_login_at = 0, None, now
    return await _open_session(session, user, ip, user_agent, now)


async def _open_session(
    session: AsyncSession, user: User, ip: str | None, user_agent: str | None, now: datetime
) -> Tokens:
    """Tạo phiên (hạn 14 ngày) và refresh token đầu tiên."""
    auth_session = AuthSession(
        id=uuid.uuid4(), user_id=user.id, created_at=now, last_seen_at=now, expires_at=now + SESSION_TTL,
        user_agent=(user_agent or "")[:300] or None, ip=ip,
    )  # fmt: skip
    session.add(auth_session)
    await session.flush()
    token = security.new_refresh_token()
    session.add(_token_row(auth_session, token, now))
    await session.flush()
    return _tokens(user, auth_session, token, now)


# ---------- refresh ----------


async def refresh(session: AsyncSession, token: str | None, now: datetime) -> Tokens | Failure:
    """Xoay refresh token (một transaction; trình tự §11.7). Dùng lại token đã xoay quá ân hạn → thu hồi phiên đó."""
    if not token:
        return Failure("INVALID_REFRESH")
    found = await repository.token_by_hash(session, security.refresh_token_hash(token))
    if found is None:
        return Failure("INVALID_REFRESH")  # không suy đoán phiên để thu hồi
    auth_session = await repository.lock_session(session, found.session_id)
    parent = await repository.lock_token(session, found.id)
    user = await repository.get_user(session, auth_session.user_id) if auth_session else None
    if (
        auth_session is None
        or parent is None
        or user is None
        or not user.is_active
        or auth_session.revoked_at is not None
        or auth_session.expires_at <= now
        or parent.expires_at <= now
    ):
        return Failure("INVALID_REFRESH")

    if parent.rotated_at is None:
        parent.rotated_at = now
        await session.flush()  # bỏ token cha khỏi ux_refresh_tokens_live trước khi tạo token con
        next_token = security.next_refresh_token(parent.id)
        child = _token_row(auth_session, next_token, now)
        session.add(child)
        await session.flush()
        parent.replaced_by = child.id
        return _tokens(user, auth_session, next_token, now)

    grace = timedelta(seconds=await settings_store.get("refresh_grace_s"))
    child = await repository.get_token(session, parent.replaced_by) if parent.replaced_by else None
    if (
        now - parent.rotated_at <= grace
        and child is not None
        and child.session_id == auth_session.id
        and child.rotated_at is None
        and child.expires_at > now
    ):
        # Refresh đồng thời hoặc client mất phản hồi trước (R33): trả lại đúng cookie kế tiếp, không tạo token mới
        next_token = security.next_refresh_token(parent.id)
        if security.refresh_token_hash(next_token) != child.token_hash:
            raise KeyMismatchError("Token kế tiếp không khớp hash: kiểm tra JWT_SECRET giữa các tiến trình")
        return _tokens(user, auth_session, next_token, now)

    await _revoke(session, auth_session, "reuse_detected", now)
    await security_events.record(session, "refresh_token_reuse", "warning", user_id=str(user.id),
                                 sid=str(auth_session.id))  # fmt: skip
    return Failure("SESSION_REVOKED")


# ---------- kiểm tra access token (mỗi request Admin) ----------


async def authenticate_access(session: AsyncSession, token: str | None, now: datetime) -> tuple[User, AuthSession]:
    """Kiểm tra JWT rồi tra phiên + người dùng theo `sid`; `sub` phải khớp chủ phiên. Không dùng được → AuthError."""
    if not token:
        raise AuthError("UNAUTHORIZED")
    try:
        claims = security.decode_access_token(token, now)
    except security.TokenError:
        raise AuthError("UNAUTHORIZED") from None
    found = await repository.session_with_user(session, claims["sid"])
    if found is None:
        raise AuthError("SESSION_REVOKED")
    auth_session, user = found
    if (
        auth_session.user_id != claims["sub"]
        or auth_session.revoked_at is not None
        or auth_session.expires_at <= now
        or not user.is_active
    ):
        raise AuthError("SESSION_REVOKED")
    if now - auth_session.last_seen_at >= LAST_SEEN_EVERY:
        auth_session.last_seen_at = now
    return user, auth_session


# ---------- thu hồi, phiên, mật khẩu ----------


async def revoke_session(session: AsyncSession, sid: uuid.UUID, reason: str, now: datetime) -> bool:
    """Thu hồi một phiên (đăng xuất, xóa một phiên trong danh sách). Trả False nếu không có hoặc đã thu hồi."""
    auth_session = await repository.lock_session(session, sid)
    if auth_session is None or auth_session.revoked_at is not None:
        return False
    await _revoke(session, auth_session, reason, now)
    return True


async def revoke_all_sessions(session: AsyncSession, user_id: int, reason: str, now: datetime) -> int:
    """Thu hồi mọi phiên của người dùng (đổi/đặt lại mật khẩu, vô hiệu hóa); khóa theo thứ tự sid; trả số phiên."""
    sessions = await repository.lock_user_sessions(session, user_id)
    for auth_session in sessions:
        await _revoke(session, auth_session, reason, now)
    return len(sessions)


async def list_sessions(session: AsyncSession, user_id: int, now: datetime) -> list[AuthSession]:
    """Các phiên đang hoạt động của người dùng (thiết bị, IP, lần dùng cuối)."""
    return await repository.active_sessions(session, user_id, now)


async def change_password(
    session: AsyncSession, user: User, current: str, new: str, ip: str | None, now: datetime
) -> Failure | None:
    """Đổi mật khẩu của chính mình (≥ 10 ký tự, khác mật khẩu cũ); thu hồi mọi phiên, kể cả phiên hiện tại."""
    if not security.verify_password(user.password_hash, current):
        return Failure("INVALID_CREDENTIALS")
    if len(new) < security.MIN_PASSWORD_LENGTH or new == current:
        return Failure("WEAK_PASSWORD")
    user.password_hash, user.password_changed_at = security.hash_password(new), now
    await revoke_all_sessions(session, user.id, "password_changed", now)
    await audit.record(session, "user.change_password", user_id=user.id, username=user.username, entity_type="user",
                       entity_id=user.id, ip=ip)  # fmt: skip
    return None


async def create_user(
    session: AsyncSession, username: str, password: str, role: str, full_name: str | None, now: datetime
) -> User:
    """Tạo tài khoản (dùng cho scripts.create_admin); mật khẩu ≥ 10 ký tự, vai trò admin | operator."""
    if len(password) < security.MIN_PASSWORD_LENGTH:
        raise ValueError("Mật khẩu phải có ít nhất 10 ký tự")
    if role not in ("admin", "operator"):
        raise ValueError("Vai trò phải là admin hoặc operator")
    user = User(username=username.strip().lower(), full_name=full_name, password_hash=security.hash_password(password),
                role=role, is_active=True, failed_login_count=0, password_changed_at=now)  # fmt: skip
    session.add(user)
    await session.flush()
    await audit.record(session, "user.create", username="system", entity_type="user", entity_id=user.id,
                       changes={"username": user.username, "role": role})  # fmt: skip
    return user


async def _revoke(session: AsyncSession, auth_session: AuthSession, reason: str, now: datetime) -> None:
    """Ghi thu hồi và phát `session_revoked` trong cùng transaction (chỉ giao sau commit)."""
    auth_session.revoked_at, auth_session.revoke_reason = now, reason
    await events.notify(session, "session_revoked", {"sid": str(auth_session.id)}, sid=str(auth_session.id))


def _token_row(auth_session: AuthSession, token: str, now: datetime) -> RefreshToken:
    """Dòng refresh token mới; hạn không vượt hạn tuyệt đối của phiên."""
    return RefreshToken(session_id=auth_session.id, token_hash=security.refresh_token_hash(token), issued_at=now,
                        expires_at=auth_session.expires_at)  # fmt: skip


def _tokens(user: User, auth_session: AuthSession, refresh_token: str, now: datetime) -> Tokens:
    """Phát access token mới cho phiên kèm refresh token cho cookie."""
    access, expires = security.create_access_token(user.id, auth_session.id, now, ACCESS_TTL)
    return Tokens(access, expires, refresh_token, auth_session.expires_at, auth_session.id, user)
