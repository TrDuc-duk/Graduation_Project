"""Tạo tài khoản admin đầu tiên (backend_design 17.1) từ ADMIN_USERNAME, ADMIN_PASSWORD (môi trường hoặc .env).

    cd backend && python -m scripts.create_admin                         # chạy trên máy (đọc backend/.env)
    set -a && . docker/.env && set +a && cd docker && \\
      docker compose run --rm -e ADMIN_USERNAME -e ADMIN_PASSWORD api python -m scripts.create_admin

Mật khẩu ≥ 10 ký tự, không bao giờ được in ra. Tài khoản đã có thì không đổi gì (chạy lại an toàn).
"""

import asyncio
import sys

from sqlalchemy.exc import IntegrityError

from app.core import timeutil
from app.core.config import get_settings
from app.core.db import get_engine, run_in_transaction
from app.modules.auth import repository, service


async def create_admin() -> tuple[int, str]:
    """Trả (mã thoát, thông báo). Thiếu biến, mật khẩu ngắn → 1; đã có tài khoản → 0, không đổi gì."""
    settings = get_settings()
    username, password = settings.admin_username.strip().lower(), settings.admin_password
    if not username or not password:
        return 1, "Thiếu ADMIN_USERNAME hoặc ADMIN_PASSWORD trong môi trường/.env."

    async def work(session):
        if await repository.user_by_username(session, username) is not None:
            return 0, f"Tài khoản {username} đã có, không thay đổi."
        user = await service.create_user(session, username, password, "admin", "Quản trị viên", timeutil.now())
        return 0, f"Đã tạo tài khoản admin {user.username} (id {user.id})."

    try:
        return await run_in_transaction(work)
    except ValueError as exc:  # mật khẩu ngắn, vai trò sai
        return 1, f"Không tạo được tài khoản: {exc}"
    except IntegrityError:  # tên sai mẫu (CHECK username: 3–50 ký tự a-z 0-9 _ . -)
        return 1, "Không tạo được tài khoản: tên đăng nhập chỉ gồm 3–50 ký tự a-z, 0-9, _ . -"
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    code, message = asyncio.run(create_admin())
    print(message, file=sys.stderr if code else sys.stdout)
    sys.exit(code)
