"""Alembic chạy bằng vai trò aqi_migrator (MIGRATION_DATABASE_URL). Migration viết bằng SQL, không autogenerate."""

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import get_settings


def include_object(obj, name, type_, reflected, compare_to):  # noqa: ARG001 — chữ ký do Alembic quy định
    """Bỏ qua bảng của extension (PostGIS, TimescaleDB) khi so sánh schema."""
    if type_ == "table" and name in ("spatial_ref_sys",):
        return False
    schema = getattr(obj, "schema", None) or ""
    return not (schema.startswith("_timescaledb") or schema.startswith("timescaledb") or schema == "topology")


def run_migrations_online() -> None:
    """Kết nối DB rồi chạy các revision."""
    url = get_settings().migration_database_url
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None, include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
