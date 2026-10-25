"""Model và dự báo: ml_models, forecast_runs, forecast_attempts, forecast_inputs, forecast_input_history, forecasts,
forecast_accuracy_daily (database_design 5.5, 7).

Thiết kế đánh số `0005_forecast`; đổi thành 0008 theo thứ tự làm (quyết định 25/10/2026). DDL theo §5.5.
Hypertable: forecasts (30 ngày, nén sau 30 ngày), forecast_inputs (30 ngày, nén sau 30 ngày),
forecast_input_history (7 ngày, xóa sau 90 ngày, R29). Không bảng nào có khóa ngoại trỏ vào hypertable.

Revision ID: 0008_forecast
Revises: 0007_settings_seed
"""

from alembic import op

revision = "0008_forecast"
down_revision = "0007_settings_seed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE ml_models (
      id                      integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      dir_name                text NOT NULL UNIQUE,
      model_version           text NOT NULL,
      bundle_sha256           text NOT NULL UNIQUE,
      algorithm               text NOT NULL DEFAULT 'xgboost',
      horizons                smallint[] NOT NULL,
      nan_policy              text NOT NULL CHECK (nan_policy IN ('no_fill','ffill3h','xgb_native_nan')),
      required_history_hours  smallint NOT NULL,
      feature_count           smallint NOT NULL,
      feature_columns_sha256  text NOT NULL,
      dataset_sha256          text,
      library_versions        jsonb,
      summary                 jsonb NOT NULL,
      status                  text NOT NULL DEFAULT 'available' CHECK (status IN ('available','invalid','missing')),
      status_reason           text,
      is_active               boolean NOT NULL DEFAULT false,
      activated_at            timestamptz,
      activated_by            bigint REFERENCES users(id) ON DELETE SET NULL,
      first_loaded_at         timestamptz NOT NULL DEFAULT now(),
      last_loaded_at          timestamptz NOT NULL DEFAULT now(),
      CHECK (NOT is_active OR status = 'available')
    );
    CREATE UNIQUE INDEX ux_ml_models_one_active ON ml_models (is_active) WHERE is_active;

    CREATE TABLE forecast_runs (
      id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      node_id           integer NOT NULL REFERENCES nodes(id),
      model_id          integer NOT NULL REFERENCES ml_models(id),
      trigger           text NOT NULL CHECK (trigger IN ('schedule','manual')),
      issue_kind        text NOT NULL CHECK (issue_kind IN ('on_time','late','catchup','manual')),
      triggered_by      bigint REFERENCES users(id) ON DELETE SET NULL,
      input_hour        timestamptz NOT NULL,
      scheduled_for     timestamptz NOT NULL,
      input_cutoff_at   timestamptz NOT NULL,
      input_convention  text NOT NULL DEFAULT 'end_label_provisional',
      input_t_samples   smallint,
      input_t_coverage  real,
      input_t_revision  smallint,
      started_at        timestamptz NOT NULL DEFAULT now(),
      issued_at         timestamptz,
      status            text NOT NULL CHECK (status IN ('running','ok','insufficient_history','no_data','error')),
      reason            text,
      missing_hours     smallint,
      eta_hours         smallint,
      attempt_count     smallint NOT NULL DEFAULT 0,
      next_attempt_at   timestamptz,
      duration_ms       integer,
      CHECK (status <> 'ok' OR issued_at IS NOT NULL)
    );
    CREATE UNIQUE INDEX ux_forecast_runs_schedule ON forecast_runs (node_id, model_id, input_hour)
      WHERE trigger = 'schedule';

    CREATE TABLE forecast_attempts (
      id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      run_id           bigint NOT NULL REFERENCES forecast_runs(id) ON DELETE CASCADE,
      attempt_no       smallint NOT NULL,
      started_at       timestamptz NOT NULL DEFAULT now(),
      finished_at      timestamptz,
      effective_now    timestamptz NOT NULL,
      input_cutoff_at  timestamptz NOT NULL,
      status           text NOT NULL CHECK (status IN ('running','ok','insufficient_history','no_data','error')),
      reason           text,
      process_id       text,
      UNIQUE (run_id, attempt_no)
    );
    CREATE INDEX ix_forecast_runs_node_time ON forecast_runs (node_id, input_hour DESC);
    CREATE INDEX ix_forecast_runs_published ON forecast_runs (node_id, input_hour DESC, issued_at DESC)
      WHERE status = 'ok' AND issue_kind IN ('on_time','late','manual');
    CREATE INDEX ix_forecast_runs_model ON forecast_runs (model_id);

    CREATE TABLE forecast_inputs (
      run_id                  bigint NOT NULL,
      issued_at               timestamptz NOT NULL,
      model_id                integer NOT NULL REFERENCES ml_models(id),
      feature_columns_sha256  text NOT NULL,
      features                double precision[] NOT NULL CHECK (cardinality(features) > 0),
      history_sha256          text NOT NULL,
      PRIMARY KEY (run_id, issued_at)
    );
    SELECT create_hypertable('forecast_inputs', by_range('issued_at', INTERVAL '30 days'));
    ALTER TABLE forecast_inputs SET (timescaledb.compress, timescaledb.compress_orderby = 'issued_at DESC');
    SELECT add_compression_policy('forecast_inputs', INTERVAL '30 days');

    CREATE TABLE forecast_input_history (
      run_id     bigint NOT NULL,
      issued_at  timestamptz NOT NULL,
      history    jsonb NOT NULL,
      PRIMARY KEY (run_id, issued_at)
    );
    SELECT create_hypertable('forecast_input_history', by_range('issued_at', INTERVAL '7 days'));
    SELECT add_retention_policy('forecast_input_history', INTERVAL '90 days');

    CREATE TABLE forecasts (
      run_id           bigint NOT NULL REFERENCES forecast_runs(id) ON DELETE CASCADE,
      horizon_h        smallint NOT NULL CHECK (horizon_h > 0),
      node_id          integer NOT NULL,
      input_hour       timestamptz NOT NULL,
      target_hour      timestamptz NOT NULL,
      predicted_aqi    double precision NOT NULL,
      persistence_aqi  smallint,
      actual_aqi       smallint,
      actual_revision  smallint,
      evaluated_at     timestamptz,
      PRIMARY KEY (run_id, horizon_h, target_hour),
      CHECK (target_hour = input_hour + make_interval(hours => horizon_h))
    );
    CREATE INDEX ix_forecasts_node_target  ON forecasts (node_id, target_hour);
    CREATE INDEX ix_forecasts_pending_eval ON forecasts (target_hour) WHERE evaluated_at IS NULL;
    SELECT create_hypertable('forecasts', by_range('target_hour', INTERVAL '30 days'));
    ALTER TABLE forecasts SET (timescaledb.compress,
      timescaledb.compress_segmentby = 'node_id', timescaledb.compress_orderby = 'target_hour DESC');
    SELECT add_compression_policy('forecasts', INTERVAL '30 days');

    CREATE TABLE forecast_accuracy_daily (
      node_id                  integer NOT NULL REFERENCES nodes(id),
      model_id                 integer NOT NULL REFERENCES ml_models(id),
      horizon_h                smallint NOT NULL,
      day                      date NOT NULL,
      issue_kind               text NOT NULL,
      n                        integer NOT NULL,
      sum_abs_err              double precision NOT NULL,
      sum_sq_err               double precision NOT NULL,
      sum_err                  double precision NOT NULL,
      sum_abs_err_persistence  double precision NOT NULL,
      n_persistence            integer NOT NULL,
      updated_at               timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (node_id, model_id, horizon_h, day, issue_kind)
    );
    CREATE INDEX ix_forecast_accuracy_daily_day ON forecast_accuracy_daily (day, horizon_h);
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE forecast_accuracy_daily;
    DROP TABLE forecasts;
    DROP TABLE forecast_input_history;
    DROP TABLE forecast_inputs;
    DROP TABLE forecast_attempts;
    DROP TABLE forecast_runs;
    DROP TABLE ml_models;
    """)
