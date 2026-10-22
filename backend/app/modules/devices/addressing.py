"""Địa chỉ LoRa và mã trạm (database_design 9). Hàm thuần, không đụng DB."""

import re
from collections.abc import Iterable

DEVICE_CODE_RE = re.compile(r"^NODE_(\d{3})$")
GATEWAY_CODE_RE = re.compile(r"^GW_(\d+)$")
MIN_ADDR, MAX_ADDR = 1, 255


def parse_device_code(code: str) -> int | None:
    """'NODE_007' → 7. Sai mẫu hoặc ngoài 1–255 thì trả None (bản ghi bị từ chối)."""
    m = DEVICE_CODE_RE.match(code or "")
    if not m:
        return None
    addr = int(m.group(1))
    return addr if MIN_ADDR <= addr <= MAX_ADDR else None


def device_code(addr: int) -> str:
    """7 → 'NODE_007' (chuỗi firmware dùng)."""
    return f"NODE_{addr:03d}"


def station_code(n: int) -> str:
    """Số từ station_code_seq → mã trạm công khai, ít nhất 3 chữ số: 7 → 'ST007', 1000 → 'ST1000'."""
    return f"ST{n:03d}"


def next_gateway_code(existing_ids: Iterable[str]) -> str:
    """Mã Gateway kế tiếp dạng GW_%03d, lớn hơn mọi mã GW_xxx đang có."""
    numbers = [int(m.group(1)) for i in existing_ids if (m := GATEWAY_CODE_RE.match(i))]
    return f"GW_{max(numbers, default=0) + 1:03d}"


def free_addresses(taken: set[int]) -> list[int]:
    """Các địa chỉ 1–255 chưa bị chiếm (đang dùng hoặc đang cách ly), từ nhỏ tới lớn."""
    return [a for a in range(MIN_ADDR, MAX_ADDR + 1) if a not in taken]
