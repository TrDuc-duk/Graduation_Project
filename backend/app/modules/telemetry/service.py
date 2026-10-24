"""Giao diện của module telemetry: lưu/tra số đo thô và log ingest."""

from datetime import datetime

from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import run_in_transaction
from app.modules.telemetry import repository
from app.modules.telemetry.models import Measurement

# Không bao giờ lưu secret của thiết bị vào log (backend_design 14.4)
SECRET_FIELDS = ("secret", "provision_key")


def strip_secrets(body: dict | None) -> dict | None:
    """Bản sao body đã bỏ secret/provision_key để lưu vào ingest_batches.payload."""
    if not isinstance(body, dict):
        return None
    return {k: v for k, v in body.items() if k not in SECRET_FIELDS}


async def start_batch(session: AsyncSession, **fields: object) -> int:
    """Ghi dòng ingest_batches ở đầu transaction ingest (để số đo tham chiếu batch_id); trả id."""
    return await repository.insert_batch(session, **fields)


async def finish_batch(session: AsyncSession, batch_id: int, received_at: datetime, **fields: object) -> None:
    """Điền thống kê cuối cùng cho batch."""
    await repository.update_batch(session, batch_id, received_at, **fields)


async def log_batch(session: AsyncSession, **fields: object) -> int:
    """Ghi một dòng ingest_batches hoàn chỉnh (heartbeat, provision)."""
    return await repository.insert_batch(session, **fields)


async def log_batch_now(**fields: object) -> None:
    """Ghi ingest_batches trong transaction riêng: dùng khi request bị từ chối hoặc transaction chính lỗi."""
    await run_in_transaction(lambda s: repository.insert_batch(s, **fields))


async def insert_measurements(session: AsyncSession, rows: list[dict]) -> list[int]:
    """Lưu số đo; trả id theo thứ tự."""
    return await repository.insert_measurements(session, rows)


async def find_matching_copies(
    session: AsyncSession, node_id: int, hashes: list[int], received_since: datetime
) -> list[Row]:
    """Bản sao còn hiệu lực của node khớp payload_hash trong cửa sổ thời gian (chống trùng, mục 6.5)."""
    if not hashes:
        return []
    return await repository.find_copies(session, node_id, hashes, received_since)


async def mark_superseded(session: AsyncSession, keys: list[tuple[int, datetime]], at: datetime) -> None:
    """Đánh dấu các bản bị thay (khóa gồm measured_at, nên bên gọi biết giờ nào cần tính lại)."""
    await repository.mark_superseded(session, keys, at)


async def nodes_with_trusted_data(session: AsyncSession, since: datetime) -> list[int]:
    """Node có số đo đáng tin nhận được từ `since`."""
    return await repository.nodes_with_trusted_data(session, since)


async def trusted_with_batch(session: AsyncSession, node_id: int, since: datetime) -> list[Row]:
    """Số đo đáng tin của node kèm thông tin batch, theo thứ tự nhận (để tính chu kỳ đo được)."""
    return await repository.trusted_with_batch(session, node_id, since)


async def readings(session: AsyncSession, node_id: int, since: datetime, limit: int) -> list[Measurement]:
    """Số đo còn hiệu lực của node từ `since` (cũ → mới), tối đa `limit` dòng gần nhất."""
    return await repository.readings(session, node_id, since, limit)


async def hourly_means(session: AsyncSession, node_id: int, since: datetime) -> list[Row]:
    """Trung bình theo giờ (nhãn h = cửa sổ (h−1, h]) của số đo dùng được cho tổng hợp, từ `since`."""
    return await repository.hourly_means(session, node_id, since)


async def latest_reading(session: AsyncSession, node_id: int) -> Measurement | None:
    """Số đo còn hiệu lực mới nhất của node, hoặc None."""
    return await repository.latest_reading(session, node_id)


async def latest_trusted_reading(session: AsyncSession, node_id: int) -> Measurement | None:
    """Số đo mới nhất dùng được cho "hiện tại" (bỏ bản cách ly, nghi dữ liệu cũ, bị thay thế), hoặc None."""
    return await repository.latest_trusted_reading(session, node_id)


async def trusted_series(session: AsyncSession, node_id: int, since: datetime) -> list[Row]:
    """Chuỗi số đo dùng được cho tổng hợp từ `since` (measured_at, aqi_instant, pm25, pm10, nhiệt độ, độ ẩm)."""
    return await repository.trusted_series(session, node_id, since)


async def last_trusted_pm25(session: AsyncSession, node_id: int, since: datetime) -> float | None:
    """PM2.5 đáng tin gần nhất của node từ `since`."""
    return await repository.last_trusted_pm25(session, node_id, since)


async def samples_for_hours(
    session: AsyncSession, node_id: int, start: datetime, end: datetime, cutoff: datetime | None = None
) -> list[Row]:
    """Số đo dùng để tổng hợp giờ trong (start, end]; `cutoff` = tính theo trạng thái tại thời điểm đó (as-of)."""
    return await repository.samples_for_hours(session, node_id, start, end, cutoff)


async def nodes_with_samples(session: AsyncSession, start: datetime, end: datetime) -> list[int]:
    """Node có số đo còn hiệu lực với measured_at trong (start, end] (để đóng/tổng hợp giờ)."""
    return await repository.nodes_with_samples(session, start, end)
