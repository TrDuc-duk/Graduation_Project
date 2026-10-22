"""Kiểm thử schema (database_design 13): migration hai chiều, kiểu cột, quyền của aqi_app."""

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from app.core.db import get_sessionmaker
from tests.conftest import alembic_config, truncate_all

# Cột duy nhất được phép kiểu real (chỉ hiển thị) — tính tới migration hiện có
ALLOWED_REAL = {("nodes", "observed_interval_iqr_ratio")}


def test_upgrade_downgrade_upgrade(migrated):
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    with migrated.connect() as conn:
        left = conn.scalars(
            text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename <> 'spatial_ref_sys'")
        ).all()
    assert left == ["alembic_version"]
    command.upgrade(cfg, "head")
    truncate_all(migrated)


def test_no_real_columns_except_allowed(migrated):
    with migrated.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND data_type = 'real'"
            )
        ).all()
    assert {(r.table_name, r.column_name) for r in rows} <= ALLOWED_REAL


def test_hypertables_and_policies(migrated):
    """measurements: chunk 7 ngày, nén sau 14, xóa sau 90; ingest_batches: 1 ngày, nén sau 2, xóa sau 14."""
    with migrated.connect() as conn:
        hypertables = set(conn.scalars(text("SELECT hypertable_name FROM timescaledb_information.hypertables")).all())
        jobs = conn.execute(
            text(
                "SELECT hypertable_name, proc_name, config FROM timescaledb_information.jobs "
                "WHERE hypertable_name IS NOT NULL"
            )
        ).all()
    assert hypertables == {"measurements", "ingest_batches"}
    policies = {(j.hypertable_name, j.proc_name): j.config for j in jobs}
    assert policies[("measurements", "policy_compression")]["compress_after"] == "14 days"
    assert policies[("measurements", "policy_retention")]["drop_after"] == "90 days"
    assert policies[("ingest_batches", "policy_compression")]["compress_after"] == "2 days"
    assert policies[("ingest_batches", "policy_retention")]["drop_after"] == "14 days"


def _insert_measurement(conn, **overrides):
    """Chèn một số đo tối thiểu (cần node 1 và Gateway GW_001)."""
    values = {
        "measured_at": "2026-10-15 07:00+00",
        "received_at": "2026-10-15 07:00+00",
        "trusted_at": "2026-10-15 07:00+00",
        "superseded_at": None,
        "qc_flags": 0,
        **overrides,
    }
    conn.execute(
        text(
            "INSERT INTO measurements (node_id, gateway_id, seq, time_source, payload_hash, measured_at, "
            "received_at, trusted_at, superseded_at, qc_flags) VALUES (1, 'GW_001', 0, 'received', 1, "
            ":measured_at, :received_at, :trusted_at, :superseded_at, :qc_flags)"
        ),
        values,
    )


@pytest.fixture
def device_rows(migrated):
    """DB sạch có Gateway GW_001 và node địa chỉ 1."""
    truncate_all(migrated)
    with migrated.begin() as conn:
        conn.execute(
            text("INSERT INTO gateways (id, lora_network_id, name, registered_via) VALUES ('GW_001', 1, 'g', 'admin')")
        )
        conn.execute(
            text(
                "INSERT INTO nodes (station_code, lora_network_id, lora_addr, name, registered_via) "
                "VALUES ('ST001', 1, 1, 'n', 'admin')"
            )
        )
    yield migrated
    truncate_all(migrated)


@pytest.mark.parametrize(
    "overrides",
    [
        {"measured_at": "2026-10-15 07:00:01+00"},  # measured_at > received_at (R6)
        {"qc_flags": 256},  # UNTRUSTED_GATEWAY mà trusted_at có giá trị (R21)
        {"trusted_at": None},  # chưa tin cậy mà không có cờ
        {"qc_flags": 4096},  # SUPERSEDED mà superseded_at NULL
        {"trusted_at": "2026-10-15 06:59+00"},  # trusted_at < received_at
    ],
)
def test_measurement_checks_reject_inconsistent_rows(device_rows, overrides):
    with pytest.raises(IntegrityError), device_rows.begin() as conn:
        _insert_measurement(conn, **overrides)


def test_late_insert_into_compressed_chunk(device_rows):
    """Dữ liệu muộn 20 ngày rơi vào chunk đã nén vẫn ghi được (database_design 13)."""
    old = "now() - interval '20 days'"
    with device_rows.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO measurements (node_id, gateway_id, seq, time_source, payload_hash, measured_at, "
                f"received_at, trusted_at) VALUES (1, 'GW_001', 0, 'received', 1, {old}, {old}, {old})"
            )
        )
        conn.execute(
            text("SELECT compress_chunk(c) FROM show_chunks('measurements', older_than => interval '14 days') c")
        )
        conn.execute(
            text(
                "INSERT INTO measurements (node_id, gateway_id, seq, time_source, payload_hash, measured_at, "
                f"received_at, trusted_at) VALUES (1, 'GW_001', 1, 'received', 2, {old}, now(), now())"
            )
        )
        assert conn.scalar(text("SELECT count(*) FROM measurements")) == 2


def test_live_address_is_unique_until_retired(device_rows):
    insert = (
        "INSERT INTO nodes (station_code, lora_network_id, lora_addr, name, registered_via) "
        "VALUES (:code, 1, 1, 'n', 'admin')"
    )
    with pytest.raises(IntegrityError), device_rows.begin() as conn:
        conn.execute(text(insert), {"code": "ST002"})
    with device_rows.begin() as conn:
        conn.execute(text("UPDATE nodes SET status = 'retired', retired_at = now() WHERE lora_addr = 1"))
        conn.execute(text(insert), {"code": "ST002"})  # node retired nhả địa chỉ


@pytest.mark.parametrize("sql", ["CREATE TABLE hack (id int)", "TRUNCATE job_runs"])
async def test_app_role_cannot_change_schema_or_truncate(migrated, sql):
    async with get_sessionmaker()() as session:
        with pytest.raises(ProgrammingError, match="permission denied"):
            await session.execute(text(sql))


def test_ccs811_type_migration_preserves_compressed_readings(device_rows):
    """Đổi kiểu TVOC vẫn giữ dữ liệu cũ và nén lại chunk đã nén."""
    with device_rows.begin() as conn:
        conn.execute(text(
            "INSERT INTO measurements (node_id, gateway_id, seq, time_source, payload_hash, "
            "measured_at, received_at, trusted_at, tvoc) VALUES "
            "(1, 'GW_001', 0, 'received', 1, now()-interval '20 days', now(), now(), 1477)"
        ))
        conn.execute(text(
            "SELECT compress_chunk(c) FROM show_chunks('measurements', older_than => interval '14 days') c"
        ))
    cfg = alembic_config()
    command.downgrade(cfg, "0003_telemetry")
    command.upgrade(cfg, "head")
    with device_rows.connect() as conn:
        assert conn.scalar(text("SELECT tvoc FROM measurements")) == 1477
        assert conn.scalar(text(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_name='measurements' AND column_name='tvoc'"
        )) == "integer"
        assert conn.scalar(text(
            "SELECT count(*) FROM timescaledb_information.chunks "
            "WHERE hypertable_name='measurements' AND is_compressed"
        )) == 1
