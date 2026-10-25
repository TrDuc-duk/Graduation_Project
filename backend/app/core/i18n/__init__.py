"""Chuỗi dịch vi/en (backend_design 11.1, U2): nhãn mức AQI, khuyến nghị, thông điệp, lỗi.

Mã (`level`, `error.code`, …) không đổi theo ngôn ngữ; chỉ trường chữ được dịch. Chuỗi nằm ở `vi.json`, `en.json`
cùng thư mục; thiếu khóa ở `en` thì dùng `vi`. API trợ lý luôn dùng `vi`.
"""

import json
from functools import cache
from pathlib import Path

from fastapi import Query, Request, Response

from app.core.config import get_settings

SUPPORTED = ("vi", "en")
FALLBACK = "vi"
_DIR = Path(__file__).parent


@cache
def _catalog(lang: str) -> dict:
    """Nạp file chuỗi của một ngôn ngữ (một lần mỗi tiến trình)."""
    return json.loads((_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def t(key: str, lang: str = FALLBACK, **params: object) -> str:
    """Chuỗi dịch theo khóa dạng "aqi.good.label"; thay `{tên}` bằng `params`. Khóa không có thì trả chính khóa."""
    for candidate in (lang, FALLBACK):
        node: object = _catalog(candidate if candidate in SUPPORTED else FALLBACK)
        for part in key.split("."):
            node = node.get(part) if isinstance(node, dict) else None
        if isinstance(node, str):
            return node.format(**params) if params else node
    return key


def pick_language(query_lang: str | None, accept_language: str | None) -> str:
    """Ngôn ngữ của response: `?lang=` nếu hợp lệ, rồi `Accept-Language` (theo q), rồi DEFAULT_LANGUAGE."""
    if query_lang and query_lang.lower() in SUPPORTED:
        return query_lang.lower()
    ranked = []
    for i, part in enumerate((accept_language or "").split(",")):
        tag, _, q = part.strip().partition(";q=")
        try:
            weight = float(q) if q else 1.0
        except ValueError:
            weight = 0.0
        ranked.append((-weight, i, tag.split("-")[0].lower()))
    for _, _, tag in sorted(ranked):
        if tag in SUPPORTED:
            return tag
    return get_settings().default_language


def language(request: Request, response: Response, lang: str | None = Query(None, max_length=8)) -> str:
    """Dependency FastAPI: chọn ngôn ngữ cho request và đặt `Content-Language`, `Vary: Accept-Language`."""
    chosen = pick_language(lang, request.headers.get("accept-language"))
    response.headers["Content-Language"] = chosen
    response.headers["Vary"] = "Accept-Language"
    return chosen
