"""Giao diện của module hourly: tính dữ liệu giờ từ số đo thô và tra chuỗi giờ/ngày (backend_design 7, 11.4)."""

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings_store
from app.modules.devices import service as devices
from app.modules.devices.models import Node
from app.modules.hourly import repository
from app.modules.hourly.aggregate import HOUR, HourAggregate, Sample, aggregate, aqi_from_pm
from app.modules.hourly.models import NodeHourly
from app.modules.telemetry import service as telemetry


@dataclass(frozen=True)
class DayPoint:
    """Một ngày (giờ Việt Nam): trung bình các giờ có dữ liệu, AQI ngày = compute_aqi của PM trung bình ngày."""

    day: date
    n_hours: int
    aqi: int | None
    pm25: float | None
    pm10: float | None
    temperature: float | None
    humidity: float | None
    co2: float | None
    tvoc: float | None


@dataclass(frozen=True)
class ProfilePoint:
    """AQI giờ trung bình tại một giờ trong ngày (0–23, giờ Việt Nam của nhãn h)."""

    hour_of_day: int
    aqi: float
    n_hours: int


async def compute_hours(
    session: AsyncSession, node: Node, first: datetime, last: datetime, cutoff: datetime | None = None
) -> dict[datetime, HourAggregate]:
    """Tính (không ghi) các giờ có nhãn từ `first` tới `last` của node; `cutoff` = theo trạng thái lúc đó.

    Dùng chung cho đóng giờ, tính lại và as-of nên mọi nơi ra cùng con số.
    """
    rows = await telemetry.samples_for_hours(session, node.id, first - HOUR, last, cutoff)
    samples = [Sample(**r._mapping) for r in rows]
    min_samples = await settings_store.get("hourly_min_samples")
    return aggregate(samples, devices.effective_interval(node), min_samples)


async def hourly_as_of(
    session: AsyncSession, node_id: int, first: datetime, last: datetime, cutoff: datetime
) -> list[HourAggregate]:
    """Dữ liệu giờ như lẽ ra tính được tại `cutoff` (R21): chỉ bản ghi đã nhận, đã được tin cậy và còn hiệu lực
    vào lúc đó. Dùng cho dự báo chạy bù, backtest, test không rò rỉ. Giờ trống không có phần tử.
    """
    node = await devices.get_node(session, node_id)
    if node is None:
        return []
    return list((await compute_hours(session, node, first, last, cutoff)).values())


async def series_hour(session: AsyncSession, node_id: int, start: datetime, end: datetime) -> list[NodeHourly]:
    """Các dòng giờ đã lưu có nhãn trong (start, end], cũ → mới (gồm cả giờ đang mở, chỉ để hiển thị)."""
    return await repository.get_hours(session, node_id, start, end)


async def series_day(session: AsyncSession, node_id: int, start: datetime, end: datetime) -> list[DayPoint]:
    """Chuỗi theo ngày từ các giờ có nhãn trong (start, end]."""
    return [
        DayPoint(
            day=r.day,
            n_hours=r.n_hours,
            aqi=aqi_from_pm(r.pm25, r.pm10),
            pm25=r.pm25,
            pm10=r.pm10,
            temperature=r.temperature,
            humidity=r.humidity,
            co2=r.co2,
            tvoc=r.tvoc,
        )
        for r in await repository.day_means(session, node_id, start, end)
    ]


async def profile(session: AsyncSession, node_id: int, since: datetime) -> list[ProfilePoint]:
    """Chu kỳ ngày: AQI giờ trung bình theo giờ trong ngày, từ các giờ đã đóng sau `since` (chỉ giờ có dữ liệu)."""
    rows = await repository.aqi_by_hour_of_day(session, node_id, since)
    return [ProfilePoint(hour_of_day=r.hour_of_day, aqi=r.aqi, n_hours=r.n_hours) for r in rows]
