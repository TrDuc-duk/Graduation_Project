"""Test thuần Python của devices (địa chỉ, mã trạm, chu kỳ) và telemetry (cờ qc)."""

from app.modules.devices import addressing
from app.modules.devices.models import Node
from app.modules.devices.service import effective_interval
from app.modules.telemetry.qc import EXCLUDE_MASK, QcFlag, is_state_trusted


def test_parse_device_code():
    assert addressing.parse_device_code("NODE_007") == 7
    assert addressing.parse_device_code("NODE_255") == 255
    for bad in ("NODE_000", "NODE_256", "NODE_7", "node_007", "NODE_0071", "", "GW_001"):
        assert addressing.parse_device_code(bad) is None


def test_station_code_never_truncates():
    assert addressing.station_code(7) == "ST007"
    assert addressing.station_code(1000) == "ST1000"


def test_next_gateway_code():
    assert addressing.next_gateway_code([]) == "GW_001"
    assert addressing.next_gateway_code(["GW_001", "GW_013", "OTHER"]) == "GW_014"


def test_free_addresses():
    free = addressing.free_addresses({1, 2, 4})
    assert free[:3] == [3, 5, 6] and free[-1] == 255
    assert addressing.free_addresses(set(range(1, 256))) == []


def test_effective_interval_priority():
    """R24: khóa → expected; không khóa → observed, thiếu thì expected; không có → None."""
    assert effective_interval(Node(interval_locked=True, expected_interval_s=300, observed_interval_s=15)) == 300
    assert effective_interval(Node(interval_locked=False, expected_interval_s=300, observed_interval_s=15)) == 15
    assert effective_interval(Node(interval_locked=False, expected_interval_s=300, observed_interval_s=None)) == 300
    assert effective_interval(Node(interval_locked=False, expected_interval_s=None, observed_interval_s=None)) is None


def test_qc_exclude_mask():
    assert EXCLUDE_MASK == 4864
    assert is_state_trusted(QcFlag.PM_SPIKE | QcFlag.TIME_ESTIMATED)
    for bad in (QcFlag.UNTRUSTED_GATEWAY, QcFlag.TIME_UNRELIABLE, QcFlag.SUPERSEDED):
        assert not is_state_trusted(bad)
