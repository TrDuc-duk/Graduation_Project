"""Giá trị mặc định của `app_settings` (backend_design 15.2), chỉ chèn khóa chưa có.

Thiết kế đánh số `0008_settings_seed`; đổi thành 0007 theo thứ tự làm (quyết định 25/10/2026).
Giá trị ghi cứng trong migration (không import code ứng dụng) để migration không đổi khi code đổi;
test đối chiếu với `settings_store.DEFAULTS`.
Downgrade chỉ xóa dòng còn đúng giá trị mặc định; cấu hình Admin đã sửa được giữ lại.

Revision ID: 0007_settings_seed
Revises: 0006_hourly
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "0007_settings_seed"
down_revision = "0006_hourly"
branch_labels = None
depends_on = None

SEED: dict[str, object] = {
    "public_horizons": list(range(3, 73, 3)),
    "forecast_confidence": {"high": [3, 6], "medium": [9, 24], "low": [27, 72]},
    "hourly_min_samples": 1,
    "hour_close_grace_s": 180,
    "gateway_offline_after_s": 900,
    "default_node_offline_after_s": 3900,
    "gateway_flush_interval_s": 30,
    "gateway_heartbeat_interval_s": 300,
    "stale_gap_factor": 2,
    "stale_send_tolerance_s": 45,
    "max_msg_gap": 20,
    "telegram_enabled": True,
    "telegram_min_severity": "warning",
    "forecast_catchup_max_hours": 24,
    "forecast_late_after_s": 600,
    "sse_max_per_ip": 50,
    "sse_max_per_admin": 10,
    "sse_max_total": 1000,
    "sse_queue_size": 100,
    "disk_warn_pct": 70,
    "disk_critical_pct": 85,
    "address_quarantine_days": 30,
    "refresh_grace_s": 30,
    "forecast_stale_max_h": 6,
    "forecast_max_attempts": 3,
    "interval_max_iqr_ratio": 0.2,
    "telemetry_gateway_limit_per_min": 120,
    "telemetry_ip_error_limit_per_min": 20,
    "telemetry_global_limit_per_min": 6000,
    "default_station_id": None,
    "pm_spike_delta": 100,
}


def _rows() -> list[dict[str, str]]:
    """Các dòng (key, value JSON) cần chèn."""
    return [{"key": k, "value": json.dumps(v)} for k, v in SEED.items()]


def upgrade() -> None:
    op.get_bind().execute(
        sa.text("INSERT INTO app_settings (key, value) VALUES (:key, CAST(:value AS jsonb)) ON CONFLICT DO NOTHING"),
        _rows(),
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM app_settings WHERE key = :key AND value = CAST(:value AS jsonb)"),
        _rows(),
    )
