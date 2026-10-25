"""Hàm bảo mật (backend_design 11.7, 14.4, 18 "Kiểm tra JWT", "Khóa refresh và cấu hình"): không cần DB."""

import base64
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core import security
from app.core.config import get_settings

NOW = datetime(2026, 10, 15, 7, 0, tzinfo=UTC)
SID = uuid.UUID("11111111-2222-3333-4444-555555555555")
SECRET = "test-jwt-secret-0123456789abcdef0123456789abcdef"  # giống tests/conftest.py


def test_password_hash_and_verify():
    h = security.hash_password("mật-khẩu-đủ-dài")
    assert h.startswith("$argon2id$")
    assert security.verify_password(h, "mật-khẩu-đủ-dài")
    assert not security.verify_password(h, "sai-mật-khẩu")
    assert not security.verify_password("không-phải-hash", "x")


def test_access_token_roundtrip_and_claims():
    token, expires = security.create_access_token(7, SID, NOW, timedelta(minutes=30))
    claims = security.decode_access_token(token, NOW + timedelta(minutes=29))
    assert (claims["sub"], claims["sid"], expires) == (7, SID, NOW + timedelta(minutes=30))
    assert isinstance(claims["jti"], str) and len(claims["jti"]) == 32
    with pytest.raises(security.TokenError):  # hết hạn theo đồng hồ của ứng dụng
        security.decode_access_token(token, NOW + timedelta(minutes=30))


def _forge(claims: dict, key: str = SECRET, algorithm: str = "HS256", headers: dict | None = None) -> str:
    return jwt.encode(claims, key, algorithm=algorithm, headers=headers)


@pytest.mark.parametrize(
    "token",
    [
        _forge({"sub": "7", "sid": str(SID), "exp": NOW + timedelta(hours=1), "jti": "x"}, algorithm="HS512"),
        _forge({"sub": "7", "sid": str(SID), "exp": NOW + timedelta(hours=1)}),  # thiếu jti
        _forge({"sub": "7", "exp": NOW + timedelta(hours=1), "jti": "x"}),  # thiếu sid
        _forge({"sub": 7, "sid": str(SID), "exp": NOW + timedelta(hours=1), "jti": "x"}),  # sub không phải chuỗi
        _forge({"sub": "7", "sid": "không-phải-uuid", "exp": NOW + timedelta(hours=1), "jti": "x"}),
        _forge({"sub": "7", "sid": str(SID), "exp": NOW + timedelta(hours=1), "jti": "x"}, key="khóa-khác" * 4),
    ],
)
def test_rejects_bad_tokens(token):
    """Thuật toán khác HS256, thiếu claim, sai kiểu, sai chữ ký → từ chối (RFC 8725 §3.1)."""
    with pytest.raises(security.TokenError):
        security.decode_access_token(token, NOW)


def test_rejects_alg_none():
    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    body = (
        base64.urlsafe_b64encode(
            f'{{"sub":"7","sid":"{SID}","exp":{int((NOW + timedelta(hours=1)).timestamp())},"jti":"x"}}'.encode()
        )
        .rstrip(b"=")
        .decode()
    )
    with pytest.raises(security.TokenError):
        security.decode_access_token(f"{header}.{body}.", NOW)


def test_refresh_token_format_and_hash():
    token = security.new_refresh_token()
    assert len(token) == 43 and "=" not in token and "+" not in token and "/" not in token
    assert security.refresh_token_hash(token) == hashlib.sha256(token.encode()).digest()
    assert security.new_refresh_token() != token


def test_next_token_fixed_vector():
    """Test vector cố định: HKDF(salt 32 byte 0, info "aqi/refresh/v1") + HMAC("refresh-next:42"), base64url không
    padding — tính độc lập theo RFC 5869 rồi ghi cứng; mọi tiến trình cùng JWT_SECRET ra cùng giá trị."""
    assert security.next_refresh_token(42) == "xVhSE79_xA1GdIiNryBUOg800ZGRKS7G3wj5_fsy99w"
    assert security.next_refresh_token(42) != security.next_refresh_token(43)


def test_short_jwt_secret_is_refused(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "ngắn")
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="32 byte"):
            security.create_access_token(1, SID, NOW, timedelta(minutes=1))
    finally:
        get_settings.cache_clear()
