"""Script scripts/set_station.py: đặt tên, khu vực, tọa độ, duyệt trạm, chọn trạm mặc định; không đụng số đo."""

import pytest

from scripts import set_station
from tests.integration.helpers import add_node, rows, scalar

URL = "/api/v1/dev/nodes"


def run(engine, *argv: str) -> dict:
    """Chạy phần áp thay đổi của script trên DB test."""
    with engine.begin() as conn:
        return set_station.apply(conn, set_station.parse_args(list(argv)))


async def test_sets_position_activates_and_marks_default(client, db):
    add_node(db, 76, status="pending")
    flags = ["--code", "st001", "--lat", "21.005", "--lng", "105.843", "--activate", "--default"]
    station = run(db, *flags, "--name", "Bách Khoa", "--district", "Hai Bà Trưng")
    assert station["status"] == "active" and station["name"] == "Bách Khoa"
    assert (round(station["lat"], 6), round(station["lng"], 6)) == (21.005, 105.843)
    assert scalar(db, "SELECT approved_at IS NOT NULL FROM nodes") is True
    assert scalar(db, "SELECT value #>> '{}' FROM app_settings WHERE key = 'default_station_id'") == "ST001"
    [node] = (await client.get(URL)).json()
    assert (node["latitude"], node["longitude"], node["district"]) == (21.005, 105.843, "Hai Bà Trưng")


async def test_only_given_fields_change(db):
    add_node(db, 1, status="pending", name="Trạm cũ")
    station = run(db, "--code", "ST001", "--lat", "10", "--lng", "106")
    assert (station["name"], station["status"]) == ("Trạm cũ", "pending")  # không --activate thì vẫn chờ duyệt
    assert rows(db, "SELECT key FROM app_settings") == []


async def test_node_without_position_has_null_coordinates(client, db):
    add_node(db, 1)
    [node] = (await client.get(URL)).json()
    assert (node["latitude"], node["longitude"]) == (None, None)


async def test_unknown_or_retired_station_is_rejected(db):
    add_node(db, 1, status="retired", retired_at="2026-10-01T00:00:00Z")
    with pytest.raises(set_station.StationError):
        run(db, "--code", "ST001", "--activate")
    with pytest.raises(set_station.StationError):
        run(db, "--code", "ST999")


@pytest.mark.parametrize("argv", [["--lat", "21"], ["--lat", "91", "--lng", "105"], ["--lat", "21", "--lng", "190"]])
def test_bad_coordinates_are_rejected(argv):
    with pytest.raises(SystemExit):
        set_station.parse_args(["--code", "ST001", *argv])
