"""Model SQLAlchemy của module hourly (database_design 5.4)."""

from datetime import datetime

from sqlalchemy import ForeignKey, Integer, SmallInteger
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION, REAL
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class NodeHourly(Base):
    """Một giờ của một node: nhãn `hour_end` = cửa sổ (h−1, h]. Giờ không có mẫu thì không có dòng."""

    __tablename__ = "node_hourly"

    node_id: Mapped[int] = mapped_column(Integer, ForeignKey("nodes.id"), primary_key=True)
    hour_end: Mapped[datetime] = mapped_column(primary_key=True)
    n_samples: Mapped[int] = mapped_column(SmallInteger)
    n_excluded: Mapped[int] = mapped_column(SmallInteger)
    n_time_estimated: Mapped[int] = mapped_column(SmallInteger)
    n_time_ambiguous: Mapped[int] = mapped_column(SmallInteger)
    expected_samples: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    coverage: Mapped[float | None] = mapped_column(REAL)
    n_pm25: Mapped[int] = mapped_column(SmallInteger)
    n_pm10: Mapped[int] = mapped_column(SmallInteger)
    n_temperature: Mapped[int] = mapped_column(SmallInteger)
    n_humidity: Mapped[int] = mapped_column(SmallInteger)
    n_co2: Mapped[int] = mapped_column(SmallInteger)
    pm25_avg: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    pm10_avg: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    temperature_avg: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    humidity_avg: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    co2_avg: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    tvoc_avg: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    pm25_max: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    pm10_max: Mapped[float | None] = mapped_column(DOUBLE_PRECISION)
    aqi: Mapped[int | None] = mapped_column(SmallInteger)
    aqi_pm25: Mapped[int | None] = mapped_column(SmallInteger)
    aqi_pm10: Mapped[int | None] = mapped_column(SmallInteger)
    qc_flags: Mapped[int] = mapped_column(Integer)
    is_closed: Mapped[bool]
    revision: Mapped[int] = mapped_column(SmallInteger)
    computed_at: Mapped[datetime]
