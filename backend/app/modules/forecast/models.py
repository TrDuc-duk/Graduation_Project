"""Model SQLAlchemy của module forecast (database_design 5.5)."""

from datetime import datetime

from sqlalchemy import ARRAY, BigInteger, Integer, SmallInteger, Text
from sqlalchemy.dialects.postgresql import DOUBLE_PRECISION, JSONB, REAL
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ForecastRun(Base):
    """Lần chạy logic cho (node, model, giờ đầu vào t); trạng thái là trạng thái lần thử cuối (R22)."""

    __tablename__ = "forecast_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    node_id: Mapped[int] = mapped_column(Integer)
    model_id: Mapped[int] = mapped_column(Integer)
    trigger: Mapped[str] = mapped_column(Text)
    issue_kind: Mapped[str] = mapped_column(Text)
    triggered_by: Mapped[int | None] = mapped_column(BigInteger)
    input_hour: Mapped[datetime]
    scheduled_for: Mapped[datetime]
    input_cutoff_at: Mapped[datetime]
    input_convention: Mapped[str] = mapped_column(Text, default="end_label_provisional")
    input_t_samples: Mapped[int | None] = mapped_column(SmallInteger)
    input_t_coverage: Mapped[float | None] = mapped_column(REAL)
    input_t_revision: Mapped[int | None] = mapped_column(SmallInteger)
    started_at: Mapped[datetime]
    issued_at: Mapped[datetime | None]
    status: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    missing_hours: Mapped[int | None] = mapped_column(SmallInteger)
    eta_hours: Mapped[int | None] = mapped_column(SmallInteger)
    attempt_count: Mapped[int] = mapped_column(SmallInteger, default=0)
    next_attempt_at: Mapped[datetime | None]
    duration_ms: Mapped[int | None]


class ForecastAttempt(Base):
    """Một lần thực thi của lần chạy: thời điểm thực thi thật, `effective_now`, mốc cắt dữ liệu, kết quả."""

    __tablename__ = "forecast_attempts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(BigInteger)
    attempt_no: Mapped[int] = mapped_column(SmallInteger)
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    effective_now: Mapped[datetime]
    input_cutoff_at: Mapped[datetime]
    status: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    process_id: Mapped[str | None] = mapped_column(Text)


class Forecast(Base):
    """Một mốc dự báo; `predicted_aqi` là giá trị gốc của model (R9); đối chiếu điền `actual_*` sau."""

    __tablename__ = "forecasts"

    run_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    horizon_h: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    target_hour: Mapped[datetime] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(Integer)
    input_hour: Mapped[datetime]
    predicted_aqi: Mapped[float] = mapped_column(DOUBLE_PRECISION)
    persistence_aqi: Mapped[int | None] = mapped_column(SmallInteger)
    actual_aqi: Mapped[int | None] = mapped_column(SmallInteger)
    actual_revision: Mapped[int | None] = mapped_column(SmallInteger)
    evaluated_at: Mapped[datetime | None]


class ForecastInput(Base):
    """184 feature đã dùng của một lần chạy, giữ lâu dài để tái hiện kết quả model (R8)."""

    __tablename__ = "forecast_inputs"

    run_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    issued_at: Mapped[datetime] = mapped_column(primary_key=True)
    model_id: Mapped[int] = mapped_column(Integer)
    feature_columns_sha256: Mapped[str] = mapped_column(Text)
    features: Mapped[list[float]] = mapped_column(ARRAY(DOUBLE_PRECISION))
    history_sha256: Mapped[str] = mapped_column(Text)


class ForecastInputHistory(Base):
    """Các dòng giờ đã dùng để dựng feature (kèm revision), giữ 90 ngày (R29)."""

    __tablename__ = "forecast_input_history"

    run_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    issued_at: Mapped[datetime] = mapped_column(primary_key=True)
    history: Mapped[list] = mapped_column(JSONB)
