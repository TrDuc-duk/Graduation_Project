"""Dữ liệu giờ và đường ống giờ: hàng đợi tính lại, node_hourly, hour_pipeline (database_design 5.4).

Thiết kế đánh số `0004_hourly`; đổi thành 0006 vì 0004, 0005 đã dùng (quyết định 25/10/2026).
`node_hourly` là bảng thường (upsert, giữ lâu dài), không phải hypertable (backend_design 3.1).

Revision ID: 0006_hourly
Revises: 0005_assistant
"""

from alembic import op

revision = "0006_hourly"
down_revision = "0005_assistant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE hourly_recompute_queue (
      node_id     integer NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
      hour_end    timestamptz NOT NULL,
      queued_at   timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (node_id, hour_end)
    );

    CREATE TABLE node_hourly (
      node_id           integer NOT NULL REFERENCES nodes(id),
      hour_end          timestamptz NOT NULL CHECK (extract(epoch FROM hour_end)::bigint % 3600 = 0),
      n_samples         smallint NOT NULL,
      n_excluded        smallint NOT NULL DEFAULT 0,
      n_time_estimated  smallint NOT NULL DEFAULT 0,
      n_time_ambiguous  smallint NOT NULL DEFAULT 0,
      expected_samples  double precision,
      coverage          real CHECK (coverage BETWEEN 0 AND 1),
      n_pm25            smallint NOT NULL,
      n_pm10            smallint NOT NULL,
      n_temperature     smallint NOT NULL,
      n_humidity        smallint NOT NULL,
      n_co2             smallint NOT NULL,
      pm25_avg          double precision,
      pm10_avg          double precision,
      temperature_avg   double precision,
      humidity_avg      double precision,
      co2_avg           double precision,
      tvoc_avg          double precision,
      pm25_max          double precision,
      pm10_max          double precision,
      aqi               smallint,
      aqi_pm25          smallint,
      aqi_pm10          smallint,
      qc_flags          integer NOT NULL DEFAULT 0,
      is_closed         boolean NOT NULL DEFAULT false,
      revision          smallint NOT NULL DEFAULT 0,
      computed_at       timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (node_id, hour_end)
    );
    CREATE INDEX ix_node_hourly_hour ON node_hourly (hour_end);

    CREATE TABLE hour_pipeline (
      hour_end                 timestamptz PRIMARY KEY CHECK (extract(epoch FROM hour_end)::bigint % 3600 = 0),
      closed_at                timestamptz,
      alerts_done_at           timestamptz,
      alerts_skipped           boolean NOT NULL DEFAULT false,
      eval_done_at             timestamptz,
      forecast_done_at         timestamptz,
      forecast_kind            text CHECK (forecast_kind IN ('on_time','late','catchup','skipped')),
      forecast_alerts_done_at  timestamptz,
      attempts                 smallint NOT NULL DEFAULT 0,
      last_error               text,
      updated_at               timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_hour_pipeline_open ON hour_pipeline (hour_end) WHERE forecast_alerts_done_at IS NULL;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE hour_pipeline; DROP TABLE node_hourly; DROP TABLE hourly_recompute_queue;")
