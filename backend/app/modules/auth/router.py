"""API xác thực `/api/v1/auth/*` (backend_design 11.7, P12, R20).

Refresh token nằm trong cookie `HttpOnly; Secure; SameSite=Strict; Path=/api/v1/auth`; access token trong body.
Phản hồi đăng nhập/refresh có `Cache-Control: no-store`. Lỗi được trả sau khi commit (thu hồi, đếm sai không mất).
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Request, Response

from app.core import ratelimit, security_events, timeutil
from app.core.db import run_in_transaction
from app.core.errors import AppError
from app.core.i18n import t
from app.core.ratelimit import client_ip
from app.modules.auth import repository, service
from app.modules.auth.deps import CurrentActor, lang_of
from app.modules.auth.schemas import ChangePasswordIn, LoginIn, SessionOut, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_NAME = "aqi_refresh"
COOKIE_PATH = "/api/v1/auth"
LOGIN_LIMIT_PER_MIN = 10  # theo IP (backend_design 14.2)
_FAILURE_STATUS = {"INVALID_CREDENTIALS": 401, "ACCOUNT_LOCKED": 423, "INVALID_REFRESH": 401, "SESSION_REVOKED": 401}


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request, response: Response) -> TokenOut:
    """Đăng nhập: tạo phiên, đặt cookie refresh, trả access token. Sai 5 lần trong 15 phút → khóa 15 phút (423)."""
    ip = client_ip(request)
    if not await ratelimit.hit(f"login:ip:{ip}", LOGIN_LIMIT_PER_MIN):
        await security_events.record_now("rate_limited", "warning", source_ip=ip, scope="login")
        raise AppError("RATE_LIMITED", 429, t("errors.RATE_LIMITED", lang_of(request)))
    now = timeutil.now()
    user_agent = request.headers.get("user-agent")
    result = await run_in_transaction(lambda s: service.login(s, body.username, body.password, ip, user_agent, now))
    return _respond(result, request, response, now)


@router.post("/refresh", response_model=TokenOut)
async def refresh(request: Request, response: Response) -> TokenOut:
    """Xoay refresh token trong cookie và trả access token mới (khoảng ân hạn 30 giây cho refresh đồng thời)."""
    now = timeutil.now()
    token = request.cookies.get(COOKIE_NAME)
    try:
        result = await run_in_transaction(lambda s: service.refresh(s, token, now))
    except service.KeyMismatchError:
        raise AppError("AUTH_CONFIG_ERROR", 500, t("errors.AUTH_CONFIG_ERROR", lang_of(request))) from None
    if isinstance(result, service.Failure):
        _clear_cookie(response)
    return _respond(result, request, response, now)


@router.post("/logout")
async def logout(actor: CurrentActor, response: Response) -> dict:
    """Đăng xuất: thu hồi phiên hiện tại và xóa cookie."""
    await run_in_transaction(lambda s: service.revoke_session(s, actor.session.id, "logout", timeutil.now()))
    _clear_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
async def me(actor: CurrentActor) -> UserOut:
    """Người dùng hiện tại (vai trò đọc từ DB mỗi request)."""
    return _user_out(actor.user)


@router.get("/sessions", response_model=list[SessionOut])
async def sessions(actor: CurrentActor) -> list[SessionOut]:
    """Các phiên đang hoạt động của chính mình."""
    items = await run_in_transaction(lambda s: service.list_sessions(s, actor.user.id, timeutil.now()))
    return [
        SessionOut(
            sid=x.id, created_at=x.created_at, last_seen_at=x.last_seen_at, expires_at=x.expires_at,
            user_agent=x.user_agent, ip=str(x.ip) if x.ip else None, current=x.id == actor.session.id,
        )
        for x in items
    ]  # fmt: skip


@router.delete("/sessions/{sid}")
async def revoke_own_session(sid: uuid.UUID, actor: CurrentActor, request: Request, response: Response) -> dict:
    """Thu hồi một phiên của chính mình (phiên của người khác → 404)."""

    async def work(s) -> bool:
        found = await repository.session_with_user(s, sid)
        if found is None or found[0].user_id != actor.user.id:
            return False
        return await service.revoke_session(s, sid, "logout", timeutil.now())

    if not await run_in_transaction(work):
        raise AppError("SESSION_NOT_FOUND", 404, t("errors.SESSION_NOT_FOUND", lang_of(request)))
    if sid == actor.session.id:
        _clear_cookie(response)
    return {"ok": True}


@router.post("/change-password")
async def change_password(body: ChangePasswordIn, actor: CurrentActor, request: Request, response: Response) -> dict:
    """Đổi mật khẩu của chính mình; mọi phiên (kể cả phiên hiện tại) bị thu hồi, phải đăng nhập lại."""

    async def work(s):
        user = await repository.get_user(s, actor.user.id)
        return await service.change_password(
            s, user, body.current_password, body.new_password, actor.ip, timeutil.now()
        )

    failure = await run_in_transaction(work)
    if failure is not None:
        status = 400 if failure.code == "WEAK_PASSWORD" else 401
        raise AppError(failure.code, status, t(f"errors.{failure.code}", lang_of(request)))
    _clear_cookie(response)
    return {"ok": True}


def _respond(result: service.Tokens | service.Failure, request: Request, response: Response, now: datetime) -> TokenOut:
    """Thành công: đặt cookie refresh + no-store; thất bại: lỗi chuẩn (sau khi transaction đã commit)."""
    response.headers["Cache-Control"] = "no-store"
    if isinstance(result, service.Failure):
        details = {"locked_until": timeutil.iso_local(result.locked_until)} if result.locked_until else {}
        raise AppError(result.code, _FAILURE_STATUS.get(result.code, 401), t(f"errors.{result.code}", lang_of(request)),
                       details)  # fmt: skip
    response.set_cookie(
        COOKIE_NAME,
        result.refresh_token,
        max_age=max(0, int((result.refresh_expires_at - now).total_seconds())),
        path=COOKIE_PATH,
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return TokenOut(access_token=result.access_token, expires_at=result.access_expires_at, user=_user_out(result.user))


def _clear_cookie(response: Response) -> None:
    """Xóa cookie refresh với đúng Path/thuộc tính lúc tạo."""
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH, httponly=True, secure=True, samesite="strict")


def _user_out(user) -> UserOut:
    return UserOut(id=user.id, username=user.username, full_name=user.full_name, role=user.role)
