"""Hàm bảo mật dùng chung (backend_design 11.7, 14.4): so sánh thời gian hằng, mật khẩu argon2id, JWT HS256,
refresh token opaque và token kế tiếp suy từ HKDF.
"""

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta
from functools import lru_cache

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import get_settings

JWT_ALGORITHM = "HS256"  # chỉ chấp nhận thuật toán do server cấu hình, không đọc từ header token (RFC 8725 §3.1)
JWT_REQUIRED_CLAIMS = ("sub", "sid", "exp", "jti")
MIN_JWT_SECRET_BYTES = 32
MIN_PASSWORD_LENGTH = 10
HKDF_SALT = bytes(32)  # 32 byte 0x00, cố định (không cần biến môi trường)
HKDF_INFO = b"aqi/refresh/v1"

_hasher = PasswordHasher()  # argon2id với tham số mặc định của thư viện


class TokenError(Exception):
    """Access token không hợp lệ (sai chữ ký, hết hạn, thiếu claim, sai thuật toán)."""


def matches_any(value: str | None, allowed: list[str]) -> bool:
    """So `value` với từng giá trị cho phép bằng phép so sánh thời gian hằng (chống đoán theo thời gian)."""
    if not value:
        return False
    found = False
    for candidate in allowed:  # không dừng sớm để thời gian không lộ vị trí khớp
        found |= hmac.compare_digest(value.encode(), candidate.encode())
    return found


# ---------- mật khẩu ----------


def hash_password(password: str) -> str:
    """Băm mật khẩu bằng argon2id (mật khẩu ≥ 10 ký tự, kiểm tra ở nơi nhận)."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Mật khẩu có khớp hash không (không ném lỗi với hash hỏng)."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError, UnicodeError, ValueError):
        return False


# ---------- access JWT ----------


def jwt_secret() -> str:
    """JWT_SECRET đã cấu hình; thiếu hoặc ngắn hơn 32 byte thì từ chối (backend_design 15.1)."""
    secret = get_settings().jwt_secret
    if len(secret.encode()) < MIN_JWT_SECRET_BYTES:
        raise RuntimeError("JWT_SECRET phải có ít nhất 32 byte (sinh bằng openssl rand -hex 32)")
    return secret


def create_access_token(user_id: int, session_id: uuid.UUID, now: datetime, ttl: timedelta) -> tuple[str, datetime]:
    """Access JWT HS256 mang `sub`, `sid`, `exp`, `iat`, `jti`; trả (token, thời điểm hết hạn)."""
    expires = now + ttl
    claims = {"sub": str(user_id), "sid": str(session_id), "iat": now, "exp": expires, "jti": secrets.token_hex(16)}
    return jwt.encode(claims, jwt_secret(), algorithm=JWT_ALGORITHM), expires


def decode_access_token(token: str, now: datetime) -> dict:
    """Kiểm tra chữ ký, hạn và kiểu claim; trả claims với `sub` (int) và `sid` (UUID). Sai bất kỳ → TokenError."""
    try:
        claims = jwt.decode(
            token,
            jwt_secret(),
            algorithms=[JWT_ALGORITHM],
            # exp kiểm tra bên dưới theo đồng hồ của ứng dụng (Clock), vẫn bắt buộc phải có claim
            options={"require": list(JWT_REQUIRED_CLAIMS), "verify_exp": False, "verify_iat": False},
            leeway=0,
        )
        if datetime.fromtimestamp(claims["exp"], now.tzinfo) <= now:  # theo đồng hồ của app (giả lập được)
            raise TokenError("hết hạn")
        if not isinstance(claims["jti"], str) or not isinstance(claims["sub"], str):
            raise TokenError("claim sai kiểu")
        return {**claims, "sub": int(claims["sub"]), "sid": uuid.UUID(claims["sid"])}
    except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
        raise TokenError(type(exc).__name__) from None


# ---------- refresh token ----------


def new_refresh_token() -> str:
    """Refresh token đầu tiên của phiên: 32 byte ngẫu nhiên (bộ sinh mật mã), base64url không padding."""
    return _b64(secrets.token_bytes(32))


def refresh_token_hash(token: str) -> bytes:
    """`token_hash` = SHA-256(UTF-8 của token); DB không bao giờ lưu token rõ."""
    return hashlib.sha256(token.encode()).digest()


@lru_cache
def _refresh_key(secret: str) -> bytes:
    """K_refresh = HKDF-SHA256(IKM = UTF8(JWT_SECRET), salt = 32 byte 0, info = "aqi/refresh/v1", L = 32)."""
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=HKDF_SALT, info=HKDF_INFO).derive(secret.encode())


def next_refresh_token(parent_id: int) -> str:
    """Token kế tiếp suy được từ id token cha (§11.7): base64url(HMAC-SHA256(K_refresh, "refresh-next:<id>")).

    Nhờ vậy refresh lặp lại trong khoảng ân hạn trả lại đúng cookie kế tiếp mà DB vẫn chỉ lưu hash.
    """
    message = f"refresh-next:{parent_id:d}".encode()
    return _b64(hmac.new(_refresh_key(jwt_secret()), message, hashlib.sha256).digest())


def _b64(raw: bytes) -> str:
    """base64url không padding."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
