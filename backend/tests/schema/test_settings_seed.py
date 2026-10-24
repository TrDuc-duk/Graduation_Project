"""Kiểm thử migration 0007_settings_seed: chèn mặc định backend_design 15.2, không ghi đè cấu hình đã có."""

import importlib.util
import json
from pathlib import Path

from alembic import command
from sqlalchemy import text

from app.core import settings_store
from tests.conftest import BACKEND_DIR, alembic_config, truncate_all


def _seed_module():
    """Nạp file migration để đọc bảng SEED (tên file bắt đầu bằng số nên không import thường được)."""
    path = Path(BACKEND_DIR) / "migrations" / "versions" / "0007_settings_seed.py"
    spec = importlib.util.spec_from_file_location("seed_0007", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _settings(engine) -> dict:
    """Toàn bộ app_settings dạng {key: value}."""
    with engine.connect() as conn:
        return {r.key: r.value for r in conn.execute(text("SELECT key, value FROM app_settings"))}


def test_seed_matches_code_defaults():
    """Migration và DEFAULTS trong code có cùng khóa và giá trị (một nguồn sự thật cho Admin và code)."""
    assert _seed_module().SEED == settings_store.DEFAULTS


def test_seed_inserts_missing_keys_and_keeps_existing(migrated):
    """DB mới tới 0006 đã có vài khóa do Admin đặt: seed chỉ thêm khóa thiếu, không ghi đè."""
    cfg = alembic_config()
    truncate_all(migrated)
    command.downgrade(cfg, "0006_hourly")
    with migrated.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO app_settings (key, value) VALUES ('hour_close_grace_s', '240'), "
                "('default_station_id', '\"ST001\"')"
            )
        )
    command.upgrade(cfg, "0007_settings_seed")
    rows = _settings(migrated)
    seed = _seed_module().SEED
    assert set(rows) == set(seed)
    assert rows["hour_close_grace_s"] == 240
    assert rows["default_station_id"] == "ST001"
    assert rows["public_horizons"] == list(range(3, 73, 3))
    assert rows["forecast_confidence"] == {"high": [3, 6], "medium": [9, 24], "low": [27, 72]}

    # Downgrade bỏ các dòng còn đúng mặc định, giữ cấu hình đã sửa
    command.downgrade(cfg, "0006_hourly")
    assert _settings(migrated) == {"hour_close_grace_s": 240, "default_station_id": "ST001"}
    command.upgrade(cfg, "head")
    truncate_all(migrated)


def test_seed_on_empty_table_gives_all_defaults(migrated):
    """DB trống: sau seed đọc qua settings_store ra đúng mặc định, JSON null giữ null."""
    cfg = alembic_config()
    truncate_all(migrated)
    command.downgrade(cfg, "0006_hourly")
    command.upgrade(cfg, "head")
    rows = _settings(migrated)
    assert rows == json.loads(json.dumps(settings_store.DEFAULTS))
    assert rows["default_station_id"] is None
    truncate_all(migrated)
