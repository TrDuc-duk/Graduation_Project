"""Kiểm thử schema migration 0006_hourly (database_design 5.4, 13): CHECK giờ tròn, coverage, FK có index."""

import pytest
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.conftest import alembic_config, truncate_all

HOURLY_TABLES = ("hourly_recompute_queue", "node_hourly", "hour_pipeline")


def _public_tables(engine) -> set[str]:
    """Tên các bảng trong schema public."""
    with engine.connect() as conn:
        return set(conn.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).all())


@pytest.fixture
def node_row(migrated):
    """DB sạch có node id 1 (để chèn dòng giờ)."""
    truncate_all(migrated)
    with migrated.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO nodes (station_code, lora_network_id, lora_addr, name, registered_via) "
                "VALUES ('ST001', 1, 1, 'n', 'admin')"
            )
        )
    yield migrated
    truncate_all(migrated)


def _insert_hourly(conn, hour_end: str, coverage: float | None = None) -> None:
    """Chèn một dòng node_hourly tối thiểu cho node 1."""
    conn.execute(
        text(
            "INSERT INTO node_hourly (node_id, hour_end, n_samples, coverage, n_pm25, n_pm10, n_temperature, "
            "n_humidity, n_co2) VALUES (1, :h, 1, :c, 1, 1, 1, 1, 1)"
        ),
        {"h": hour_end, "c": coverage},
    )


def test_downgrade_to_0005_drops_only_hourly_tables(migrated):
    """Hạ về 0005 bỏ đúng 3 bảng giờ, nâng lại thì có lại; bảng cũ không bị ảnh hưởng."""
    cfg = alembic_config()
    command.downgrade(cfg, "0005_assistant")
    tables = _public_tables(migrated)
    assert not tables & set(HOURLY_TABLES)
    assert {"measurements", "nodes", "assistant_calls"} <= tables
    command.upgrade(cfg, "head")
    assert set(HOURLY_TABLES) <= _public_tables(migrated)
    truncate_all(migrated)


@pytest.mark.parametrize("hour_end", ["2026-10-15 07:30+00", "2026-10-15 07:00:01+00"])
def test_hour_end_must_be_whole_hour(node_row, hour_end):
    """Nhãn giờ h phải là giờ tròn (cửa sổ (h−1, h])."""
    with pytest.raises(IntegrityError), node_row.begin() as conn:
        _insert_hourly(conn, hour_end)
    with pytest.raises(IntegrityError), node_row.begin() as conn:
        conn.execute(text("INSERT INTO hour_pipeline (hour_end) VALUES (:h)"), {"h": hour_end})


def test_hour_end_in_other_offset_is_still_whole_hour(node_row):
    """Giờ Việt Nam trùng ranh giới giờ UTC: 14:00+07 là giờ tròn."""
    with node_row.begin() as conn:
        _insert_hourly(conn, "2026-10-15 14:00+07", coverage=1.0)
        assert conn.scalar(text("SELECT count(*) FROM node_hourly")) == 1


@pytest.mark.parametrize("coverage", [-0.1, 1.01])
def test_coverage_between_0_and_1(node_row, coverage):
    with pytest.raises(IntegrityError), node_row.begin() as conn:
        _insert_hourly(conn, "2026-10-15 07:00+00", coverage=coverage)


def test_hourly_defaults(node_row):
    """Dòng mới: chưa đóng, revision 0, không cờ; hour_pipeline chưa có bước nào xong."""
    with node_row.begin() as conn:
        _insert_hourly(conn, "2026-10-15 07:00+00")
        row = conn.execute(text("SELECT is_closed, revision, qc_flags, n_excluded FROM node_hourly")).one()
        conn.execute(text("INSERT INTO hour_pipeline (hour_end) VALUES ('2026-10-15 07:00+00')"))
        pipe = conn.execute(text("SELECT closed_at, attempts, alerts_skipped FROM hour_pipeline")).one()
    assert tuple(row) == (False, 0, 0, 0)
    assert tuple(pipe) == (None, 0, False)


def test_recompute_queue_cascades_with_node(node_row):
    """Xóa hẳn node (chỉ khi chưa có dữ liệu) kéo theo hàng đợi tính lại."""
    with node_row.begin() as conn:
        conn.execute(text("INSERT INTO hourly_recompute_queue (node_id, hour_end) VALUES (1, '2026-10-15 07:00+00')"))
        conn.execute(text("DELETE FROM nodes WHERE id = 1"))
        assert conn.scalar(text("SELECT count(*) FROM hourly_recompute_queue")) == 0


def test_forecast_kind_check(node_row):
    with pytest.raises(IntegrityError), node_row.begin() as conn:
        conn.execute(text("INSERT INTO hour_pipeline (hour_end, forecast_kind) VALUES ('2026-10-15 07:00+00', 'x')"))


def test_hourly_foreign_keys_have_index(migrated):
    """Mọi FK của bảng giờ có index với cột FK đứng đầu (database_design 13)."""
    with migrated.connect() as conn:
        missing = conn.execute(
            text(
                """
                SELECT c.conrelid::regclass::text AS tbl, a.attname AS col
                FROM pg_constraint c
                JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
                WHERE c.contype = 'f' AND c.conrelid::regclass::text = ANY(:tables)
                  AND NOT EXISTS (
                    SELECT 1 FROM pg_index i WHERE i.indrelid = c.conrelid AND i.indkey[0] = c.conkey[1]
                  )
                """
            ),
            {"tables": list(HOURLY_TABLES)},
        ).all()
    assert missing == []


def test_node_hourly_is_plain_table(migrated):
    """node_hourly là bảng thường (upsert, giữ lâu dài), không phải hypertable (backend_design 3.1)."""
    with migrated.connect() as conn:
        names = set(conn.scalars(text("SELECT hypertable_name FROM timescaledb_information.hypertables")).all())
    assert not names & set(HOURLY_TABLES)
