"""Hàm bảo mật dùng chung."""

import hmac


def matches_any(value: str | None, allowed: list[str]) -> bool:
    """So `value` với từng giá trị cho phép bằng phép so sánh thời gian hằng (chống đoán theo thời gian)."""
    if not value:
        return False
    found = False
    for candidate in allowed:  # không dừng sớm để thời gian không lộ vị trí khớp
        found |= hmac.compare_digest(value.encode(), candidate.encode())
    return found
