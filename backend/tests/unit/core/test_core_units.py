"""Test phần thuần Python của core: thời gian, cấu hình, so sánh secret, backoff outbox."""

from datetime import UTC, datetime, timedelta

from app.core import timeutil
from app.core.config import Settings
from app.core.locks import address_key
from app.core.outbox import backoff
from app.core.security import matches_any


def test_floor_hour_and_local_time():
    t = datetime(2026, 10, 15, 7, 37, 5, 123, tzinfo=UTC)
    assert timeutil.floor_hour(t) == datetime(2026, 10, 15, 7, tzinfo=UTC)
    assert timeutil.to_local(t).hour == 14  # UTC+7


def test_fixed_clock_is_used_by_now():
    fixed = timeutil.FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
    timeutil.set_clock(fixed)
    try:
        assert timeutil.now() == datetime(2026, 1, 1, tzinfo=UTC)
        fixed.advance(seconds=30)
        assert timeutil.now() == datetime(2026, 1, 1, 0, 0, 30, tzinfo=UTC)
    finally:
        timeutil.set_clock(timeutil.Clock())


def test_gateway_secrets_split_from_env_string():
    s = Settings(database_url="x", provision_key="k", gateway_secrets="old-key, super-secret-key,")
    assert s.gateway_secrets == ["old-key", "super-secret-key"]


def test_scheduler_only_for_all_and_worker():
    base = {"database_url": "x", "provision_key": "k", "scheduler_enabled": True}
    assert Settings(**base, app_role="all").scheduler_active
    assert Settings(**base, app_role="worker").scheduler_active
    assert not Settings(**base, app_role="api").scheduler_active
    assert not Settings(**{**base, "scheduler_enabled": False}, app_role="all").scheduler_active


def test_matches_any_secret():
    assert matches_any("super-secret-key", ["a", "super-secret-key"])
    assert not matches_any("wrong", ["super-secret-key"])
    assert not matches_any(None, ["super-secret-key"])
    assert not matches_any("", [""])


def test_outbox_backoff_doubles_and_caps_at_10_minutes():
    assert backoff(1) == timedelta(seconds=2)
    assert backoff(5) == timedelta(seconds=32)
    assert backoff(20) == timedelta(minutes=10)


def test_address_key():
    assert address_key(1, 7) == 263
    assert address_key(2, 255) == 767
