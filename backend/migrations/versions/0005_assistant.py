"""Nhật ký lệnh gọi của trợ lý Xiaozhi (database_design 5.7).

Thiết kế đánh số `0007_assistant`; đổi thành 0005 vì 0004 đã dùng cho dải TVOC (quyết định 23/10/2026).
Bảng log: không khóa ngoại tới node để vẫn ghi được khi trạm không tồn tại. Job xóa sau 30 ngày chưa có.

Revision ID: 0005_assistant
Revises: 0004_ccs811_range
"""

from alembic import op

revision = "0005_assistant"
down_revision = "0004_ccs811_range"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE assistant_calls (
      id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      called_at     timestamptz NOT NULL DEFAULT now(),
      tool          text NOT NULL,
      params        jsonb,
      station_code  text,
      node_id       integer,
      status        text NOT NULL CHECK (status IN ('ok','error')),
      error_code    text,
      duration_ms   integer
    );
    CREATE INDEX ix_assistant_calls_time ON assistant_calls (called_at DESC);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE assistant_calls;")
