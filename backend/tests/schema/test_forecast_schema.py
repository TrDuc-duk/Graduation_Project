"""Kiểm thử schema migration 0008_forecast (database_design 5.5, 7, 13)."""

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.conftest import alembic_config, truncate_all

FORECAST_TABLES = {
    "ml_models", "forecast_runs", "forecast_attempts", "forecast_inputs", "forecast_input_history", "forecasts",
    "forecast_accuracy_daily",
}  # fmt: skip


def _tables(engine) -> set[str]:
    with engine.connect() as conn:
        return set(conn.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).all())


@pytest.fixture
def base(migrated):
    """DB sạch có node 1 và model 1 (chưa active)."""
    truncate_all(migrated)
    with migrated.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO nodes (station_code, lora_network_id, lora_addr, name, registered_via) "
                "VALUES ('ST001', 1, 1, 'n', 'admin')"
            )
        )
        conn.execute(text(_model_sql("v1-no_fill", "sha-1")))
    yield migrated
    truncate_all(migrated)


def _model_sql(dir_name: str, sha: str, active: bool = False, status: str = "available") -> str:
    return (
        "INSERT INTO ml_models (dir_name, model_version, bundle_sha256, horizons, nan_policy, required_history_hours, "
        f"feature_count, feature_columns_sha256, summary, is_active, status) VALUES ('{dir_name}', 'v1', '{sha}', "
        f"'{{3,6}}', 'no_fill', 73, 184, 'f', '{{}}', {str(active).lower()}, '{status}')"
    )


def _run_sql(trigger: str = "schedule", status: str = "running", issued: str = "NULL") -> str:
    kind = "manual" if trigger == "manual" else "on_time"
    return (
        "INSERT INTO forecast_runs (node_id, model_id, trigger, issue_kind, input_hour, scheduled_for, "
        f"input_cutoff_at, status, issued_at) VALUES (1, 1, '{trigger}', '{kind}', "
        f"'2026-10-15 07:00+00', '2026-10-15 07:05+00', '2026-10-15 07:05+00', '{status}', {issued}) RETURNING id"
    )


def test_downgrade_to_0007_drops_forecast_tables(migrated):
    cfg = alembic_config()
    truncate_all(migrated)
    command.downgrade(cfg, "0007_settings_seed")
    assert not _tables(migrated) & FORECAST_TABLES
    command.upgrade(cfg, "head")
    assert _tables(migrated) >= FORECAST_TABLES
    truncate_all(migrated)


def test_forecast_hypertables_and_policies(migrated):
    """forecasts, forecast_inputs: chunk 30 ngày, nén sau 30 ngày; forecast_input_history: 7 ngày, xóa sau 90."""
    with migrated.connect() as conn:
        dims = dict(
            conn.execute(
                text(
                    "SELECT hypertable_name, time_interval FROM timescaledb_information.dimensions "
                    "WHERE hypertable_name LIKE 'forecast%'"
                )
            ).all()
        )
        jobs = conn.execute(
            text(
                "SELECT hypertable_name, proc_name, config FROM timescaledb_information.jobs "
                "WHERE hypertable_name LIKE 'forecast%'"
            )
        ).all()
    assert {k: v.days for k, v in dims.items()} == {"forecasts": 30, "forecast_inputs": 30, "forecast_input_history": 7}
    policies = {(j.hypertable_name, j.proc_name): j.config for j in jobs}
    assert policies[("forecasts", "policy_compression")]["compress_after"] == "30 days"
    assert policies[("forecast_inputs", "policy_compression")]["compress_after"] == "30 days"
    assert policies[("forecast_input_history", "policy_retention")]["drop_after"] == "90 days"
    assert ("forecasts", "policy_retention") not in policies  # dự báo giữ lâu dài (P8)


def test_only_one_active_model(base):
    """ux_ml_models_one_active: kích hoạt hai model → lỗi."""
    with base.begin() as conn:
        conn.execute(text("UPDATE ml_models SET is_active = true"))
    with pytest.raises(IntegrityError), base.begin() as conn:
        conn.execute(text(_model_sql("v2", "sha-2", active=True)))


def test_active_model_must_be_available(base):
    with pytest.raises(IntegrityError), base.begin() as conn:
        conn.execute(text(_model_sql("v3", "sha-3", active=True, status="invalid")))


def test_one_scheduled_run_per_hour_but_many_manual(base):
    """ux_forecast_runs_schedule (R22): hai lần chạy `schedule` cùng (node, model, giờ) → lỗi; `manual` thì được."""
    with base.begin() as conn:
        conn.execute(text(_run_sql()))
        conn.execute(text(_run_sql("manual")))
        conn.execute(text(_run_sql("manual")))
    with pytest.raises(IntegrityError), base.begin() as conn:
        conn.execute(text(_run_sql()))


def test_ok_run_needs_issued_at_and_target_hour_check(base):
    with pytest.raises(IntegrityError), base.begin() as conn:
        conn.execute(text(_run_sql(status="ok")))
    with base.begin() as conn:
        run_id = conn.scalar(text(_run_sql(status="ok", issued="'2026-10-15 07:05+00'")))
    with pytest.raises(IntegrityError), base.begin() as conn:  # target_hour phải = input_hour + horizon
        conn.execute(
            text(
                "INSERT INTO forecasts (run_id, horizon_h, node_id, input_hour, target_hour, predicted_aqi) "
                "VALUES (:r, 3, 1, '2026-10-15 07:00+00', '2026-10-15 11:00+00', 100.5)"
            ),
            {"r": run_id},
        )
    with base.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO forecasts (run_id, horizon_h, node_id, input_hour, target_hour, predicted_aqi) "
                "VALUES (:r, 3, 1, '2026-10-15 07:00+00', '2026-10-15 10:00+00', 100.5)"
            ),
            {"r": run_id},
        )
        assert conn.scalar(text("SELECT predicted_aqi FROM forecasts")) == 100.5


def test_forecast_foreign_keys_with_index(migrated):
    """FK dùng để tra hoặc xóa theo cha có index với cột FK đứng đầu (database_design 13)."""
    expected = {
        ("forecast_runs", "node_id"), ("forecast_runs", "model_id"), ("forecast_attempts", "run_id"),
        ("forecasts", "run_id"), ("forecast_accuracy_daily", "node_id"),
    }  # fmt: skip
    with migrated.connect() as conn:
        indexed = set(
            conn.execute(
                text(
                    """
                    SELECT c.conrelid::regclass::text, a.attname
                    FROM pg_constraint c
                    JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
                    WHERE c.contype = 'f' AND c.conrelid::regclass::text LIKE 'forecast%'
                      AND EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = c.conrelid AND i.indkey[0] = c.conkey[1])
                    """
                )
            ).all()
        )
    assert expected <= indexed
