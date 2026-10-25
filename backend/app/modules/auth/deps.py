"""Dependency FastAPI cho khu Admin (backend_design 11.7, 11.8, P7): kiểm tra access token + phiên mỗi request,
kiểm tra vai trò. Frontend ẩn nút theo vai trò chỉ cho gọn; quyền thật luôn kiểm tra ở đây.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from app.core import timeutil
from app.core.db import run_in_transaction
from app.core.errors import AppError
from app.core.i18n import pick_language, t
from app.core.ratelimit import client_ip
from app.modules.auth import service
from app.modules.auth.models import AuthSession, User


@dataclass(frozen=True)
class Actor:
    """Người đang gọi API Admin: tài khoản, phiên, IP (để ghi audit)."""

    user: User
    session: AuthSession
    ip: str | None

    @property
    def is_admin(self) -> bool:
        return self.user.role == "admin"


def lang_of(request: Request) -> str:
    """Ngôn ngữ thông điệp lỗi theo `?lang=` / Accept-Language."""
    return pick_language(request.query_params.get("lang"), request.headers.get("accept-language"))


def bearer_token(request: Request) -> str | None:
    """Access token từ header `Authorization: Bearer …`."""
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else None


async def current_actor(request: Request) -> Actor:
    """Đã đăng nhập: JWT hợp lệ và phiên còn hiệu lực (tra DB mỗi request). Không → 401 UNAUTHORIZED/SESSION_REVOKED."""
    token = bearer_token(request)
    try:
        user, auth_session = await run_in_transaction(lambda s: service.authenticate_access(s, token, timeutil.now()))
    except service.AuthError as exc:
        raise AppError(exc.code, 401, t(f"errors.{exc.code}", lang_of(request))) from None
    return Actor(user, auth_session, client_ip(request))


CurrentActor = Annotated[Actor, Depends(current_actor)]


def require_role(*roles: str) -> Callable[[Actor], Awaitable[Actor]]:
    """Dependency: chỉ cho các vai trò trong `roles`, vd require_role("admin"); sai vai trò → 403 FORBIDDEN."""

    async def check(request: Request, actor: CurrentActor) -> Actor:
        if actor.user.role not in roles:
            raise AppError("FORBIDDEN", 403, t("errors.FORBIDDEN", lang_of(request)))
        return actor

    return check


AdminOnly = Annotated[Actor, Depends(require_role("admin"))]
