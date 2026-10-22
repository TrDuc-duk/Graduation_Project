"""Lưu đủ dải TVOC CCS811 (0–32768 ppb), vượt smallint có dấu.

Revision ID: 0004_ccs811_range
Revises: 0003_telemetry
"""

from alembic import op
from sqlalchemy import text

revision = "0004_ccs811_range"
down_revision = "0003_telemetry"
branch_labels = None
depends_on = None


def _alter_tvoc_type(data_type: str) -> None:
    """Đổi kiểu cột, khôi phục trạng thái nén của các chunk cũ sau khi đổi."""
    connection = op.get_bind()
    chunks = connection.scalars(text(
        "SELECT format('%I.%I', chunk_schema, chunk_name) "
        "FROM timescaledb_information.chunks "
        "WHERE hypertable_schema = 'public' AND hypertable_name = 'measurements' AND is_compressed"
    )).all()
    for chunk in chunks:
        connection.execute(text("SELECT decompress_chunk(CAST(:chunk AS regclass))"), {"chunk": chunk})
    op.execute(f"ALTER TABLE measurements ALTER COLUMN tvoc TYPE {data_type}")
    for chunk in chunks:
        connection.execute(text("SELECT compress_chunk(CAST(:chunk AS regclass))"), {"chunk": chunk})


def upgrade() -> None:
    _alter_tvoc_type("integer")


def downgrade() -> None:
    # PostgreSQL từ chối rollback nếu có TVOC >32767; không cắt hoặc xóa số đo.
    _alter_tvoc_type("smallint")
