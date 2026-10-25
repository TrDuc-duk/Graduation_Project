"""API xác thực qua HTTP (D1b, backend_design 11.7, 14.2, 18 "Đăng nhập cơ bản", "API: phân quyền")."""

from datetime import timedelta

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.db import run_in_transaction
from app.core.errors import register_error_handlers
from app.modules.auth import service
from app.modules.auth.deps import require_role
from scripts import create_admin as create_admin_script
from tests.conftest import T0
from tests.integration.helpers import rows, scalar

AUTH = "/api/v1/auth"
PASSWORD = "mat-khau-quan-tri-1"


@pytest.fixture
async def admin(db, clock):
    await run_in_transaction(lambda s: service.create_user(s, "admin", PASSWORD, "admin", None, T0))
    await run_in_transaction(lambda s: service.create_user(s, "operator1", PASSWORD, "operator", None, T0))


async def login(client, username="admin", password=PASSWORD):
    return await client.post(f"{AUTH}/login", json={"username": username, "password": password},
                             headers={"User-Agent": "pytest-browser"})  # fmt: skip


def cookie_of(response) -> str:
    """Giá trị cookie refresh trong Set-Cookie (cookie Secure: tự gửi lại bằng header khi test qua http)."""
    header = response.headers["set-cookie"]
    return header.split(";", 1)[0].split("=", 1)[1]


def bearer(response) -> dict:
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_login_sets_strict_cookie_and_no_store(client, admin):
    r = await login(client)
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer" and body["user"] == {"id": 1, "username": "admin", "full_name": None,
                                                                "role": "admin"}  # fmt: skip
    assert body["expires_at"] == "2026-10-15T14:30:00+07:00" and r.headers["cache-control"] == "no-store"
    cookie = r.headers["set-cookie"].lower()
    for attr in ("httponly", "secure", "samesite=strict", "path=/api/v1/auth", "max-age=1209600"):
        assert attr in cookie
    assert "refresh" not in body  # refresh token không bao giờ nằm trong body


async def test_wrong_password_and_lock(client, admin):
    r = await login(client, password="sai")
    assert (r.status_code, r.json()["error"]["code"]) == (401, "INVALID_CREDENTIALS")
    for _ in range(4):
        r = await login(client, password="sai")
    assert (r.status_code, r.json()["error"]["code"]) == (423, "ACCOUNT_LOCKED")
    assert r.json()["error"]["details"]["locked_until"] == "2026-10-15T14:15:00+07:00"


async def test_refresh_with_cookie_rotates(client, admin, clock):
    first = await login(client)
    clock.advance(minutes=5)
    r = await client.post(f"{AUTH}/refresh", headers={"Cookie": f"aqi_refresh={cookie_of(first)}"})
    assert r.status_code == 200 and cookie_of(r) != cookie_of(first) and r.headers["cache-control"] == "no-store"
    assert (await client.get(f"{AUTH}/me", headers=bearer(r))).json()["username"] == "admin"
    missing = await client.post(f"{AUTH}/refresh")
    assert (missing.status_code, missing.json()["error"]["code"]) == (401, "INVALID_REFRESH")


async def test_me_logout_and_revoked(client, admin):
    r = await login(client)
    assert (await client.get(f"{AUTH}/me")).json()["error"]["code"] == "UNAUTHORIZED"
    assert (await client.get(f"{AUTH}/me", headers={"Authorization": "Bearer garbage"})).status_code == 401
    out = await client.post(f"{AUTH}/logout", headers=bearer(r))
    assert out.status_code == 200
    cleared = out.headers["set-cookie"].lower()
    assert 'aqi_refresh=""' in cleared and "max-age=0" in cleared and "path=/api/v1/auth" in cleared
    again = await client.get(f"{AUTH}/me", headers=bearer(r))
    assert (again.status_code, again.json()["error"]["code"]) == (401, "SESSION_REVOKED")


async def test_sessions_list_and_revoke_own_only(client, admin):
    a = await login(client)
    b = await login(client)
    other = await login(client, username="operator1")
    listed = (await client.get(f"{AUTH}/sessions", headers=bearer(a))).json()
    assert len(listed) == 2 and sum(x["current"] for x in listed) == 1 and listed[0]["user_agent"] == "pytest-browser"
    b_sid = next(x["sid"] for x in listed if not x["current"])
    assert (await client.delete(f"{AUTH}/sessions/{b_sid}", headers=bearer(a))).status_code == 200
    assert (await client.get(f"{AUTH}/me", headers=bearer(b))).status_code == 401
    op_sid = (await client.get(f"{AUTH}/sessions", headers=bearer(other))).json()[0]["sid"]
    r = await client.delete(f"{AUTH}/sessions/{op_sid}", headers=bearer(a))
    assert (r.status_code, r.json()["error"]["code"]) == (404, "SESSION_NOT_FOUND")
    assert (await client.get(f"{AUTH}/me", headers=bearer(other))).status_code == 200


async def test_change_password_logs_out_everywhere(client, admin):
    a, b = await login(client), await login(client)
    bad = await client.post(f"{AUTH}/change-password", headers=bearer(a),
                            json={"current_password": PASSWORD, "new_password": "ngan"})  # fmt: skip
    assert bad.status_code == 422  # < 10 ký tự bị chặn ngay ở schema
    r = await client.post(f"{AUTH}/change-password", headers=bearer(a),
                          json={"current_password": PASSWORD, "new_password": "mat-khau-moi-12345"})  # fmt: skip
    assert r.status_code == 200
    for t in (a, b):
        assert (await client.get(f"{AUTH}/me", headers=bearer(t))).status_code == 401
    assert (await login(client, password="mat-khau-moi-12345")).status_code == 200


async def test_change_password_is_audited_without_values(client, admin, db):
    a = await login(client)
    await client.post(f"{AUTH}/change-password", headers=bearer(a),
                      json={"current_password": PASSWORD, "new_password": "mat-khau-moi-12345"})  # fmt: skip
    [log] = rows(db, "SELECT action, changes FROM audit_logs WHERE action = 'user.change_password'")
    assert log.changes is None


async def test_unknown_fields_rejected(client, admin):
    r = await client.post(f"{AUTH}/login", json={"username": "admin", "password": PASSWORD, "role": "admin"})
    assert (r.status_code, r.json()["error"]["code"]) == (422, "INVALID_PARAMS")


async def test_login_rate_limit_per_ip(client, admin, db):
    for _ in range(10):
        await login(client)
    r = await login(client)
    assert (r.status_code, r.json()["error"]["code"]) == (429, "RATE_LIMITED")
    assert scalar(db, "SELECT count(*) FROM security_events WHERE kind = 'rate_limited'") == 1


async def test_key_mismatch_returns_server_error(client, admin, monkeypatch):
    first = await login(client)
    await client.post(f"{AUTH}/refresh", headers={"Cookie": f"aqi_refresh={cookie_of(first)}"})

    def mismatch(*_):
        raise service.KeyMismatchError("x")

    monkeypatch.setattr(service, "refresh", lambda *a, **k: mismatch())
    r = await client.post(f"{AUTH}/refresh", headers={"Cookie": f"aqi_refresh={cookie_of(first)}"})
    assert (r.status_code, r.json()["error"]["code"]) == (500, "AUTH_CONFIG_ERROR")


async def test_require_role_blocks_operator(client, admin):
    """Backend kiểm tra vai trò (frontend chỉ ẩn nút): operator gọi route chỉ dành cho admin → 403."""
    app = FastAPI()
    register_error_handlers(app)

    admin_dep = Depends(require_role("admin"))

    @app.get("/admin-only", dependencies=[admin_dep])
    async def admin_only():
        return {"ok": True}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        op = await login(client, username="operator1")
        ad = await login(client)
        r = await c.get("/admin-only", headers=bearer(op))
        assert (r.status_code, r.json()["error"]["code"]) == (403, "FORBIDDEN")
        assert (await c.get("/admin-only", headers=bearer(ad))).status_code == 200


async def test_audit_logs_endpoint(client, admin, db):
    assert (await client.get("/api/v1/admin/audit-logs")).status_code == 401
    op = await login(client, username="operator1")
    r = (await client.get("/api/v1/admin/audit-logs", headers=bearer(op), params={"action": "user.create"})).json()
    assert (
        r["total"] == 2 and r["page"] == 1 and {x["changes"]["username"] for x in r["items"]} == {"admin", "operator1"}
    )
    assert (
        await client.get("/api/v1/admin/audit-logs", headers=bearer(op), params={"page_size": 500})
    ).status_code == 422


async def test_last_seen_updates_at_most_once_a_minute(client, admin, clock, db):
    r = await login(client)
    clock.advance(seconds=30)
    await client.get(f"{AUTH}/me", headers=bearer(r))
    first = rows(db, "SELECT last_seen_at FROM auth_sessions")[0].last_seen_at
    clock.advance(seconds=40)
    await client.get(f"{AUTH}/me", headers=bearer(r))
    assert first == T0 and rows(db, "SELECT last_seen_at FROM auth_sessions")[0].last_seen_at == T0 + timedelta(
        seconds=70
    )


async def test_create_admin_script(db, monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "Chu.Du_An")
    monkeypatch.setenv("ADMIN_PASSWORD", "ngan")
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        code, msg = await create_admin_script.create_admin()
        assert code == 1 and "10 ký tự" in msg and "ngan" not in msg
        monkeypatch.setenv("ADMIN_PASSWORD", "mat-khau-du-dai-1")
        get_settings.cache_clear()
        assert (await create_admin_script.create_admin())[0] == 0
        assert (await create_admin_script.create_admin())[1].endswith("đã có, không thay đổi.")
        assert rows(db, "SELECT username, role FROM users") == [("chu.du_an", "admin")]
    finally:
        get_settings.cache_clear()
