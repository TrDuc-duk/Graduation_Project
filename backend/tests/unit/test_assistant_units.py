"""Phần thuần Python của API trợ lý: kiểm tra tham số, định dạng số và thời gian trong câu tiếng Việt."""

from datetime import UTC, datetime

import pytest

from app.core.errors import AssistantError
from app.modules.assistant.service import parse_horizons, parse_hours, say_number, say_time


@pytest.mark.parametrize(("raw", "hours"), [(None, 24), ("", 24), ("1", 1), ("72", 72)])
def test_parse_hours(raw, hours):
    assert parse_hours(raw) == hours


@pytest.mark.parametrize("raw", ["0", "73", "-5", "2.5", "abc"])
def test_parse_hours_rejects(raw):
    with pytest.raises(AssistantError) as e:
        parse_hours(raw)
    assert (e.value.code, e.value.http_status) == ("INVALID_PARAMS", 422)


def test_parse_horizons_default_dedup_sorted():
    assert parse_horizons(None) == [3, 6, 12, 24]
    assert parse_horizons("24, 3,3,72") == [3, 24, 72]


@pytest.mark.parametrize("raw", ["0", "4", "75", "3,x", ","])
def test_parse_horizons_rejects(raw):
    with pytest.raises(AssistantError):
        parse_horizons(raw)


def test_say_number_uses_vietnamese_decimal_and_keeps_missing():
    assert say_number(43.0, "µg/m³") == "43,0 µg/m³"
    assert say_number(124.4, digits=0) == "124"
    assert say_number(None, "%") == "không có số đo"


def test_say_time_is_local_vietnam_time():
    assert say_time(datetime(2026, 10, 15, 17, 35, tzinfo=UTC)) == "00:35 ngày 16/10"
