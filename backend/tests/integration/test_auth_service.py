"""Đăng nhập, phiên, refresh xoay vòng (backend_design 11.7, 18 "Đăng nhập cơ bản", "Phiên đăng nhập (R20)",
"Kiểm tra JWT và hạn refresh", "Khóa refresh và cấu hình", "Transaction thu hồi") với DB thật.
"""

import asyncio
import json
from datetime import timedelta

import psycopg
import pytest

from app.core import security
from app.core.config import get_settings
from app.core.db import get_sessionmaker, run_in_transaction
from app.core.events import _libpq_dsn
from app.modules.auth import repository, service
from tests.conftest import T0
from tests.integration.helpers import execute, rows, scalar

PASSWORD = "mat-khau-quan-tri-1"


@pytest.fixture
async def user(db):
    return await run_in_transaction(lambda s: service.create_user(s, "Admin", PASSWORD, "admin", "Quản trị", T0))


async def login(username="admin", password=PASSWORD, now=T0):
    return await run_in_transaction(lambda s: service.login(s, username, password, "10.0.0.1", "pytest", now))


async def refresh(token, now):
    return await run_in_transaction(lambda s: service.refresh(s, token, now))


async def access(token, now):
    return await run_in_transaction(lambda s: service.authenticate_access(s, token, now))


async def test_login_creates_session_and_first_token(db, user):
    t = await login()
    assert isinstance(t, service.Tokens) and t.user.username == "admin"
    [s] = rows(db, "SELECT * FROM auth_sessions")
    assert (s.id, s.user_agent, str(s.ip), s.expires_at) == (
        t.session_id,
        "pytest",
        "10.0.0.1",
        T0 + timedelta(days=14),
    )
    [tok] = rows(db, "SELECT * FROM refresh_tokens")
    assert bytes(tok.token_hash) == security.refresh_token_hash(t.refresh_token) and tok.expires_at == s.expires_at
    assert rows(db, "SELECT username FROM users")[0].username == "admin"  # tên đăng nhập lưu chữ thường
    found_user, found_session = await access(t.access_token, T0 + timedelta(minutes=1))
    assert (found_user.id, found_session.id) == (user.id, t.session_id)


async def test_wrong_password_five_times_locks_for_15_minutes(db, user):
    for i in range(4):
        assert (await login(password="sai", now=T0 + timedelta(minutes=i))).code == "INVALID_CREDENTIALS"
    locked = await login(password="sai", now=T0 + timedelta(minutes=4))
    assert (locked.code, locked.locked_until) == ("ACCOUNT_LOCKED", T0 + timedelta(minutes=19))
    assert (await login(now=T0 + timedelta(minutes=10))).code == "ACCOUNT_LOCKED"  # đúng mật khẩu vẫn bị khóa
    assert isinstance(await login(now=T0 + timedelta(minutes=19)), service.Tokens)
    assert scalar(db, "SELECT count(*) FROM security_events WHERE kind = 'admin_login_failed'") == 5
    assert scalar(db, "SELECT count(*) FROM security_events WHERE kind = 'admin_locked'") == 1
    assert scalar(db, "SELECT count(*) FROM audit_logs WHERE action = 'user.locked'") == 1


async def test_failures_outside_window_do_not_lock(db, user):
    for i in range(4):
        await login(password="sai", now=T0 + timedelta(minutes=i))
    assert (await login(password="sai", now=T0 + timedelta(minutes=20))).code == "INVALID_CREDENTIALS"


async def test_unknown_or_inactive_user(db, user):
    assert (await login(username="nobody")).code == "INVALID_CREDENTIALS"
    execute(db, "UPDATE users SET is_active = false")
    assert (await login()).code == "INVALID_CREDENTIALS"


async def test_revoked_session_rejects_valid_jwt_immediately(db, user):
    """Thu hồi phiên → request tiếp theo với access JWT còn hạn nhận SESSION_REVOKED (R20)."""
    t = await login()
    await run_in_transaction(lambda s: service.revoke_session(s, t.session_id, "logout", T0))
    with pytest.raises(service.AuthError) as exc:
        await access(t.access_token, T0 + timedelta(minutes=1))
    assert exc.value.code == "SESSION_REVOKED"


async def test_sub_must_match_session_owner_and_role_read_from_db(db, user):
    t = await login()
    forged, _ = security.create_access_token(user.id + 1, t.session_id, T0, timedelta(minutes=30))
    with pytest.raises(service.AuthError):
        await access(forged, T0)
    execute(db, "UPDATE users SET role = 'operator'")
    found_user, _ = await access(t.access_token, T0)
    assert found_user.role == "operator"  # đổi vai trò có hiệu lực ngay, không cần thu hồi phiên


async def test_refresh_rotates_exactly_one_new_token(db, user):
    t0 = await login()
    t1 = await refresh(t0.refresh_token, T0 + timedelta(minutes=1))
    assert isinstance(t1, service.Tokens) and t1.refresh_token != t0.refresh_token
    toks = rows(db, "SELECT id, rotated_at, replaced_by, expires_at FROM refresh_tokens ORDER BY id")
    assert len(toks) == 2 and toks[0].replaced_by == toks[1].id and toks[1].rotated_at is None
    assert t1.refresh_token == security.next_refresh_token(toks[0].id)
    assert toks[1].expires_at == T0 + timedelta(days=14)  # không kéo dài hạn tuyệt đối của phiên


async def test_concurrent_refresh_with_same_cookie(db, user):
    """Hai refresh đồng thời cùng cookie: cùng access mới và cùng cookie kế tiếp, một lần xoay, không thu hồi."""
    t0 = await login()
    now = T0 + timedelta(minutes=1)
    a, b = await asyncio.gather(refresh(t0.refresh_token, now), refresh(t0.refresh_token, now))
    assert isinstance(a, service.Tokens) and isinstance(b, service.Tokens)
    assert a.refresh_token == b.refresh_token
    assert scalar(db, "SELECT count(*) FROM refresh_tokens") == 2
    assert rows(db, "SELECT revoked_at FROM auth_sessions")[0].revoked_at is None


async def test_lost_response_retry_gets_same_next_cookie(db, user):
    """R33: client mất phản hồi, thử lại trong 30 giây bằng cookie cũ → nhận lại đúng cookie kế tiếp; dùng cookie đó
    refresh tiếp được; thử lại không đổi rotated_at hay hạn token."""
    t0 = await login()
    t1 = await refresh(t0.refresh_token, T0 + timedelta(seconds=10))
    rotated = rows(db, "SELECT rotated_at FROM refresh_tokens ORDER BY id")[0].rotated_at
    again = await refresh(t0.refresh_token, T0 + timedelta(seconds=35))
    assert again.refresh_token == t1.refresh_token
    assert rows(db, "SELECT rotated_at FROM refresh_tokens ORDER BY id")[0].rotated_at == rotated
    t2 = await refresh(t1.refresh_token, T0 + timedelta(seconds=40))
    assert isinstance(t2, service.Tokens)
    assert rows(db, "SELECT revoked_at FROM auth_sessions")[0].revoked_at is None


async def test_reuse_after_grace_revokes_only_that_session(db, user):
    t0 = await login()
    other = await login()
    await refresh(t0.refresh_token, T0)
    reused = await refresh(t0.refresh_token, T0 + timedelta(seconds=31))
    assert reused.code == "SESSION_REVOKED"
    by_id = {r.id: r for r in rows(db, "SELECT id, revoked_at, revoke_reason FROM auth_sessions")}
    assert by_id[t0.session_id].revoke_reason == "reuse_detected"
    assert by_id[other.session_id].revoked_at is None
    assert scalar(db, "SELECT count(*) FROM security_events WHERE kind = 'refresh_token_reuse'") == 1


async def test_reuse_when_next_token_already_rotated(db, user):
    t0 = await login()
    t1 = await refresh(t0.refresh_token, T0)
    await refresh(t1.refresh_token, T0 + timedelta(seconds=5))
    assert (await refresh(t0.refresh_token, T0 + timedelta(seconds=10))).code == "SESSION_REVOKED"


async def test_refresh_refused_when_expired_or_user_disabled(db, user):
    t0 = await login()
    assert (await refresh(t0.refresh_token, T0 + timedelta(days=14))).code == "INVALID_REFRESH"
    execute(db, "UPDATE users SET is_active = false")
    assert (await refresh(t0.refresh_token, T0 + timedelta(minutes=1))).code == "INVALID_REFRESH"
    assert (await refresh("token-lạ", T0)).code == "INVALID_REFRESH"
    assert scalar(db, "SELECT count(*) FROM refresh_tokens") == 1  # không tạo token mới


async def test_change_password_revokes_every_session(db, user):
    t0, t1 = await login(), await login()
    u = await run_in_transaction(lambda s: repository.get_user(s, user.id))
    assert (
        await run_in_transaction(lambda s: service.change_password(s, u, "sai", "mat-khau-moi-123", None, T0))
    ).code == "INVALID_CREDENTIALS"
    assert (
        await run_in_transaction(lambda s: service.change_password(s, u, PASSWORD, "ngan", None, T0))
    ).code == "WEAK_PASSWORD"

    async def change(s):
        return await service.change_password(s, await repository.get_user(s, user.id), PASSWORD, "mat-khau-moi-123",
                                             None, T0)  # fmt: skip

    assert await run_in_transaction(change) is None
    assert {r.revoke_reason for r in rows(db, "SELECT revoke_reason FROM auth_sessions")} == {"password_changed"}
    for t in (t0, t1):
        with pytest.raises(service.AuthError):
            await access(t.access_token, T0)
    assert isinstance(await login(password="mat-khau-moi-123"), service.Tokens)


class Listener:
    """Kết nối LISTEN aqi_events riêng để kiểm tra NOTIFY session_revoked (chỉ giao sau commit)."""

    async def __aenter__(self):
        self.conn = await psycopg.AsyncConnection.connect(_libpq_dsn(), autocommit=True)
        await self.conn.execute("LISTEN aqi_events")
        return self

    async def collect(self, timeout: float = 0.5) -> list[dict]:
        out = []
        try:
            async with asyncio.timeout(timeout):
                async for n in self.conn.notifies():
                    out.append(json.loads(n.payload))
        except TimeoutError:
            pass
        return [e for e in out if e["type"] == "session_revoked"]

    async def __aexit__(self, *exc):
        await self.conn.close()


async def test_revocations_notify_once_per_sid_and_rollback_notifies_nothing(db, user):
    t0, t1 = await login(), await login()
    async with Listener() as listen:
        async with get_sessionmaker()() as s:
            await s.begin()
            await service.revoke_all_sessions(s, user.id, "admin", T0)
            await s.rollback()
        assert await listen.collect() == []
        assert {r.revoked_at for r in rows(db, "SELECT revoked_at FROM auth_sessions")} == {None}

        assert await run_in_transaction(lambda s: service.revoke_all_sessions(s, user.id, "user_disabled", T0)) == 2
        events = await listen.collect()
    assert sorted(e["sid"] for e in events) == sorted([str(t0.session_id), str(t1.session_id)])


async def test_revoke_and_refresh_race(db, user):
    """Thu hồi đang giữ khóa phiên → refresh chờ; sau commit thu hồi thì refresh không được."""
    t0 = await login()
    async with get_sessionmaker()() as holder:
        await holder.begin()
        await service.revoke_session(holder, t0.session_id, "logout", T0)
        task = asyncio.create_task(refresh(t0.refresh_token, T0 + timedelta(seconds=1)))
        await asyncio.sleep(0.3)
        assert not task.done()
        await holder.commit()
    assert (await task).code == "INVALID_REFRESH"


async def test_key_mismatch_is_server_error_not_reuse(db, user, monkeypatch):
    """Đổi JWT_SECRET giữa hai lần refresh trong ân hạn: hash kế tiếp lệch → lỗi cấu hình, không thu hồi phiên."""
    t0 = await login()
    await refresh(t0.refresh_token, T0)
    monkeypatch.setenv("JWT_SECRET", "another-secret-0123456789abcdef0123456789abcdef")
    get_settings.cache_clear()
    try:
        with pytest.raises(service.KeyMismatchError):
            await refresh(t0.refresh_token, T0 + timedelta(seconds=5))
    finally:
        get_settings.cache_clear()
    assert rows(db, "SELECT revoked_at FROM auth_sessions")[0].revoked_at is None
