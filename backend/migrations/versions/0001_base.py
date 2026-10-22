"""Nền tảng: core, auth, audit (database_design 5.1).

Revision ID: 0001_base
Revises:
"""

from alembic import op

revision = "0001_base"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extension do superuser tạo trong docker/db/100_aqi_roles.sh; migration chỉ kiểm tra
    op.execute("""
    DO $$
    BEGIN
      IF (SELECT count(*) FROM pg_extension WHERE extname IN ('timescaledb', 'postgis')) < 2 THEN
        RAISE EXCEPTION 'Thiếu extension timescaledb/postgis (xem docker/db/100_aqi_roles.sh)';
      END IF;
    END $$;
    """)

    op.execute("""
    CREATE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      NEW.updated_at := now();
      RETURN NEW;
    END $$;

    -- ===== auth =====
    CREATE TABLE users (
      id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      username            text NOT NULL UNIQUE CHECK (username ~ '^[a-z0-9_.-]{3,50}$'),
      full_name           text,
      password_hash       text NOT NULL,
      role                text NOT NULL CHECK (role IN ('admin','operator')),
      is_active           boolean NOT NULL DEFAULT true,
      last_login_at       timestamptz,
      failed_login_count  smallint NOT NULL DEFAULT 0,
      locked_until        timestamptz,
      password_changed_at timestamptz NOT NULL DEFAULT now(),
      created_at          timestamptz NOT NULL DEFAULT now(),
      updated_at          timestamptz NOT NULL DEFAULT now()
    );
    CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users
      FOR EACH ROW EXECUTE FUNCTION set_updated_at();

    CREATE TABLE auth_sessions (
      id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
      user_id        bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      created_at     timestamptz NOT NULL DEFAULT now(),
      last_seen_at   timestamptz NOT NULL DEFAULT now(),
      expires_at     timestamptz NOT NULL,
      revoked_at     timestamptz,
      revoke_reason  text CHECK (revoke_reason IN
                     ('logout','reuse_detected','password_changed','user_disabled','admin','expired')),
      user_agent     text,
      ip             inet
    );
    CREATE INDEX ix_auth_sessions_user_active ON auth_sessions (user_id) WHERE revoked_at IS NULL;

    CREATE TABLE refresh_tokens (
      id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      session_id    uuid NOT NULL REFERENCES auth_sessions(id) ON DELETE CASCADE,
      token_hash    bytea NOT NULL UNIQUE,
      issued_at     timestamptz NOT NULL DEFAULT now(),
      expires_at    timestamptz NOT NULL,
      rotated_at    timestamptz,
      replaced_by   bigint REFERENCES refresh_tokens(id)
    );
    CREATE INDEX ix_refresh_tokens_session ON refresh_tokens (session_id);
    CREATE UNIQUE INDEX ux_refresh_tokens_live ON refresh_tokens (session_id) WHERE rotated_at IS NULL;

    -- ===== audit =====
    CREATE TABLE audit_logs (
      id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      occurred_at  timestamptz NOT NULL DEFAULT now(),
      user_id      bigint REFERENCES users(id) ON DELETE SET NULL,
      username     text,
      action       text NOT NULL,
      entity_type  text,
      entity_id    text,
      changes      jsonb,
      ip           inet
    );
    CREATE INDEX ix_audit_logs_time   ON audit_logs (occurred_at DESC);
    CREATE INDEX ix_audit_logs_entity ON audit_logs (entity_type, entity_id, occurred_at DESC);

    -- ===== core =====
    CREATE TABLE app_settings (
      key         text PRIMARY KEY,
      value       jsonb NOT NULL,
      updated_by  bigint REFERENCES users(id) ON DELETE SET NULL,
      updated_at  timestamptz NOT NULL DEFAULT now()
    );
    CREATE TRIGGER trg_app_settings_updated_at BEFORE UPDATE ON app_settings
      FOR EACH ROW EXECUTE FUNCTION set_updated_at();

    CREATE TABLE job_runs (
      id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      job          text NOT NULL,
      process_id   text,
      started_at   timestamptz NOT NULL DEFAULT now(),
      finished_at  timestamptz,
      status       text NOT NULL CHECK (status IN ('running','ok','error','skipped')),
      stats        jsonb,
      error        text
    );
    CREATE INDEX ix_job_runs_job_time ON job_runs (job, started_at DESC);

    CREATE TABLE security_events (
      id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      occurred_at  timestamptz NOT NULL DEFAULT now(),
      kind         text NOT NULL,
      severity     text NOT NULL CHECK (severity IN ('info','warning','critical')),
      source_ip    inet,
      gateway_id   text,
      node_id      integer,
      user_id      bigint REFERENCES users(id) ON DELETE SET NULL,
      details      jsonb
    );
    CREATE INDEX ix_security_events_time ON security_events (occurred_at DESC);
    CREATE INDEX ix_security_events_kind ON security_events (kind, occurred_at DESC);

    CREATE TABLE outbox_events (
      id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      created_at    timestamptz NOT NULL DEFAULT now(),
      kind          text NOT NULL,
      partition_key text,
      payload       jsonb NOT NULL,
      available_at  timestamptz NOT NULL DEFAULT now(),
      attempts      smallint NOT NULL DEFAULT 0,
      status        text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','done','failed')),
      processed_at  timestamptz,
      last_error    text
    );
    CREATE INDEX ix_outbox_events_pending   ON outbox_events (available_at, id) WHERE status = 'pending';
    CREATE INDEX ix_outbox_events_partition ON outbox_events (partition_key, id) WHERE status = 'pending';
    CREATE INDEX ix_outbox_events_failed    ON outbox_events (created_at DESC) WHERE status = 'failed';

    CREATE UNLOGGED TABLE rate_counters (
      key           text NOT NULL,
      window_start  timestamptz NOT NULL,
      count         integer NOT NULL,
      PRIMARY KEY (key, window_start)
    );
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE rate_counters, outbox_events, security_events, job_runs, app_settings,
               audit_logs, refresh_tokens, auth_sessions, users;
    DROP FUNCTION set_updated_at();
    """)
