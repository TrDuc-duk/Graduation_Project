"""Dữ liệu thô: log ingest và số đo, hypertable có nén và retention (database_design 5.3).

`hourly_recompute_queue` để sang 0004 (M2) theo quyết định 15/10/2026.

Revision ID: 0003_telemetry
Revises: 0002_devices
"""

from alembic import op

revision = "0003_telemetry"
down_revision = "0002_devices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE ingest_batches (
      id              bigint GENERATED ALWAYS AS IDENTITY,
      received_at     timestamptz NOT NULL DEFAULT now(),
      kind            text NOT NULL CHECK (kind IN ('telemetry','heartbeat','provision')),
      gateway_id      text,
      remote_ip       inet,
      http_status     smallint NOT NULL,
      item_count      smallint NOT NULL DEFAULT 0,
      accepted        smallint NOT NULL DEFAULT 0,
      duplicates      smallint NOT NULL DEFAULT 0,
      superseded      smallint NOT NULL DEFAULT 0,
      heartbeats      smallint NOT NULL DEFAULT 0,
      rejected        smallint NOT NULL DEFAULT 0,
      has_msg_id      boolean,
      stale_suspected boolean NOT NULL DEFAULT false,
      stale_reason    text CHECK (stale_reason IN ('gateway_silent','after_rejection')),
      possible_age_s  integer,
      error           text,
      payload         jsonb,
      processing_ms   integer,
      attempts        smallint NOT NULL DEFAULT 1,
      PRIMARY KEY (id, received_at)
    );
    CREATE INDEX ix_ingest_batches_gateway ON ingest_batches (gateway_id, received_at DESC);
    CREATE INDEX ix_ingest_batches_stale   ON ingest_batches (received_at DESC) WHERE stale_suspected;
    SELECT create_hypertable('ingest_batches', by_range('received_at', INTERVAL '1 day'));
    ALTER TABLE ingest_batches SET (timescaledb.compress,
      timescaledb.compress_segmentby = 'gateway_id', timescaledb.compress_orderby = 'received_at DESC');
    SELECT add_compression_policy('ingest_batches', INTERVAL '2 days');
    SELECT add_retention_policy('ingest_batches', INTERVAL '14 days');

    CREATE TABLE measurements (
      id            bigint GENERATED ALWAYS AS IDENTITY,
      node_id       integer NOT NULL REFERENCES nodes(id),
      measured_at   timestamptz NOT NULL,
      received_at   timestamptz NOT NULL,
      max_age_s     integer CHECK (max_age_s >= 0),
      trusted_at    timestamptz,
      superseded_at timestamptz,
      gateway_id    text NOT NULL REFERENCES gateways(id),
      batch_id      bigint,
      seq           smallint NOT NULL,
      msg_id        smallint CHECK (msg_id BETWEEN 0 AND 255),
      time_source   text NOT NULL CHECK (time_source IN ('device','received','estimated','unreliable')),
      pm25          double precision,
      pm10          double precision,
      co2           smallint,
      tvoc          smallint,
      temperature   double precision,
      humidity      double precision,
      battery_pct   smallint,
      aqi_instant   smallint,
      qc_flags      integer NOT NULL DEFAULT 0,
      payload_hash  bigint NOT NULL,
      PRIMARY KEY (id, measured_at),
      CHECK (measured_at <= received_at),
      CHECK (((qc_flags & 256) <> 0) = (trusted_at IS NULL)),
      CHECK (((qc_flags & 4096) <> 0) = (superseded_at IS NOT NULL)),
      CHECK (trusted_at IS NULL OR trusted_at >= received_at)
    );
    CREATE INDEX ix_measurements_node_time     ON measurements (node_id, measured_at DESC);
    CREATE INDEX ix_measurements_node_received ON measurements (node_id, received_at DESC);
    SELECT create_hypertable('measurements', by_range('measured_at', INTERVAL '7 days'));
    ALTER TABLE measurements SET (timescaledb.compress,
      timescaledb.compress_segmentby = 'node_id', timescaledb.compress_orderby = 'measured_at DESC');
    SELECT add_compression_policy('measurements', INTERVAL '14 days');
    SELECT add_retention_policy('measurements', INTERVAL '90 days');
    """)


def downgrade() -> None:
    op.execute("DROP TABLE measurements, ingest_batches;")
