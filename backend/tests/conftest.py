"""Cấu hình test dùng chung.

- Test unit (tests/unit) không cần DB.
- Test cần DB dùng fixture `db`: DB thật (docker-compose.dev.yml hoặc service của CI) đã migrate tới head;
  sau mỗi test xóa sạch dữ liệu để test sau bắt đầu từ DB rỗng.
"""

import os
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text

os.environ.setdefault("SCHEDULER_ENABLED", "false")  # test tự gọi job, không để scheduler chạy
os.environ.setdefault("ENABLE_DEV_ENDPOINTS", "true")  # test cả API dev
os.environ["ASSISTANT_TOKEN"] = "test-assistant-token"  # bật API trợ lý với token cố định của test
os.environ["JWT_SECRET"] = "test-jwt-secret-0123456789abcdef0123456789abcdef"  # khóa cố định (≥ 32 byte) cho test

from app.core import ratelimit, settings_store, timeutil  # noqa: E402
from app.core.config import get_settings  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Thời điểm cố định cho test cần đồng hồ giả
T0 = datetime(2026, 10, 15, 7, 0, 0, tzinfo=UTC)


def alembic_config() -> Config:
    """Cấu hình Alembic trỏ tới backend/alembic.ini."""
    return Config(os.path.join(BACKEND_DIR, "alembic.ini"))


@pytest.fixture(scope="session")
def migrator():
    """Engine đồng bộ bằng vai trò aqi_migrator (chủ bảng): dùng để migrate và dọn dữ liệu."""
    engine = create_engine(get_settings().migration_database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def migrated(migrator):
    """Đưa DB lên revision mới nhất một lần cho cả phiên test.

    Test xóa sạch dữ liệu sau mỗi lần chạy, nên chỉ chạy trên DB tên *_test (hoặc khi ALLOW_TEST_DB_WIPE=1,
    như DB tạm của CI) để không xóa nhầm DB aqi đang nhận số đo thật.
    """
    if not (migrator.url.database or "").endswith("_test") and os.environ.get("ALLOW_TEST_DB_WIPE") != "1":
        pytest.exit(f"Từ chối chạy test trên DB '{migrator.url.database}': test sẽ xóa dữ liệu. Dùng DB *_test.", 2)
    command.upgrade(alembic_config(), "head")
    return migrator


def truncate_all(engine) -> None:
    """Xóa dữ liệu mọi bảng của ứng dụng, đặt lại bộ đếm ID và dòng seed (mạng LoRa 'default')."""
    with engine.begin() as conn:
        tables = conn.scalars(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename NOT IN ('alembic_version', 'spatial_ref_sys')"
            )
        ).all()
        if tables:
            conn.execute(text(f"TRUNCATE {', '.join(tables)} RESTART IDENTITY CASCADE"))
        if "lora_networks" in tables:
            conn.execute(text("INSERT INTO lora_networks (code, name) VALUES ('default', 'Mạng mặc định')"))
        if conn.scalar(text("SELECT to_regclass('station_code_seq')")):
            conn.execute(text("ALTER SEQUENCE station_code_seq RESTART"))


@pytest.fixture
async def db(migrated):
    """DB sạch cho một test; trả engine của aqi_migrator để test đọc/ghi trực tiếp khi cần."""
    truncate_all(migrated)
    settings_store.clear_cache()
    await ratelimit.reset()
    yield migrated
    timeutil.set_clock(timeutil.Clock())


@pytest.fixture
def clock():
    """Đồng hồ giả bắt đầu ở T0; code gọi timeutil.now() sẽ thấy giờ này."""
    fixed = timeutil.FixedClock(T0)
    timeutil.set_clock(fixed)
    yield fixed
    timeutil.set_clock(timeutil.Clock())


@pytest.fixture
async def client():
    """Client HTTP gọi thẳng vào ứng dụng (không mở cổng mạng)."""
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
