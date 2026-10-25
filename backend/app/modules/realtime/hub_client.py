"""Hàng đợi sự kiện của một client SSE (R12): hữu hạn, gộp sự kiện cùng trạm, đầy thì chỉ còn `resync`."""

import asyncio
import itertools

# Sự kiện trạng thái: chỉ cần bản mới nhất của mỗi (loại, trạm) (backend_design 11.6)
MERGED_TYPES = frozenset({"measurement", "hourly", "station_status"})
RESYNC = {"type": "resync"}


class ClientQueue:
    """Hàng đợi tối đa `maxsize` sự kiện. Gộp theo (loại, mã trạm) để `measurement` không xóa mất `hourly`.

    Đầy: xóa hết và chỉ giữ một `resync` để client tải lại qua REST, nên bộ nhớ không tăng theo client chậm.
    """

    def __init__(self, maxsize: int):
        self.maxsize = maxsize
        self._items: dict[tuple, dict] = {}
        self._seq = itertools.count()
        self._wake = asyncio.Event()

    def offer(self, event: dict) -> None:
        """Thêm sự kiện (không chặn). Gọi từ EventHub."""
        if event.get("type") in MERGED_TYPES:
            key: tuple = (event["type"], event.get("station_id"))
            self._items.pop(key, None)  # bản cũ bị thay, bản mới xếp cuối hàng
        else:
            key = ("seq", next(self._seq))
        if len(self._items) >= self.maxsize:
            self._items.clear()
            key, event = ("resync",), RESYNC
        self._items[key] = event
        self._wake.set()

    async def get(self) -> dict:
        """Lấy sự kiện cũ nhất; chờ nếu hàng đợi trống."""
        while not self._items:
            self._wake.clear()
            await self._wake.wait()
        key = next(iter(self._items))
        return self._items.pop(key)

    def __len__(self) -> int:
        return len(self._items)
