"""Model SQLAlchemy của module pipeline (database_design 5.4)."""

from datetime import datetime

from sqlalchemy import SmallInteger, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class HourPipeline(Base):
    """Tiến độ đường ống của một nhãn giờ: mỗi bước có cột thời điểm xong; NULL = chưa xong."""

    __tablename__ = "hour_pipeline"

    hour_end: Mapped[datetime] = mapped_column(primary_key=True)
    closed_at: Mapped[datetime | None]
    alerts_done_at: Mapped[datetime | None]
    alerts_skipped: Mapped[bool]
    eval_done_at: Mapped[datetime | None]
    forecast_done_at: Mapped[datetime | None]
    forecast_kind: Mapped[str | None] = mapped_column(Text)
    forecast_alerts_done_at: Mapped[datetime | None]
    attempts: Mapped[int] = mapped_column(SmallInteger)
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime]
