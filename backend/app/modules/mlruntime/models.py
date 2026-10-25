"""Model SQLAlchemy của module mlruntime (database_design 5.5)."""

from datetime import datetime

from sqlalchemy import ARRAY, BigInteger, Integer, SmallInteger, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class MlModel(Base):
    """Một phiên bản model = một thư mục con của MODEL_DIR (không sửa, không xóa để tái hiện dự báo cũ, R8)."""

    __tablename__ = "ml_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dir_name: Mapped[str] = mapped_column(Text)
    model_version: Mapped[str] = mapped_column(Text)
    bundle_sha256: Mapped[str] = mapped_column(Text)
    algorithm: Mapped[str] = mapped_column(Text, default="xgboost")
    horizons: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger))
    nan_policy: Mapped[str] = mapped_column(Text)
    required_history_hours: Mapped[int] = mapped_column(SmallInteger)
    feature_count: Mapped[int] = mapped_column(SmallInteger)
    feature_columns_sha256: Mapped[str] = mapped_column(Text)
    dataset_sha256: Mapped[str | None] = mapped_column(Text)
    library_versions: Mapped[dict | None] = mapped_column(JSONB)
    summary: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, default="available")
    status_reason: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=False)
    activated_at: Mapped[datetime | None]
    activated_by: Mapped[int | None] = mapped_column(BigInteger)
    first_loaded_at: Mapped[datetime]
    last_loaded_at: Mapped[datetime]
