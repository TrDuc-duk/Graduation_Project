"""Đặt thông tin trạm, duyệt trạm và chọn trạm mặc định (thay tạm thao tác Admin cho tới M4).

Chỉ sửa bảng `nodes` (tên, khu vực, tọa độ, trạng thái duyệt) và `app_settings.default_station_id`;
không thêm hay sửa số đo. Dùng DATABASE_URL như backend (đọc từ biến môi trường hoặc backend/.env).

Chạy từ thư mục backend (dạng module để import được app):
    python -m scripts.set_station --code ST001 --name "Bách Khoa" --district "Hai Bà Trưng" \\
        --lat 21.0050 --lng 105.8430 --activate --default
    python -m scripts.set_station --code ST001 --lat 21.0050 --lng 105.8430     # chỉ đặt tọa độ
"""

import argparse
import json
import sys

from sqlalchemy import Connection, create_engine, text

from app.core.config import get_settings


class StationError(Exception):
    """Tham số không hợp lệ hoặc trạm không đổi được (thông báo in ra cho người chạy)."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Đọc tham số dòng lệnh; vĩ độ và kinh độ phải đi cùng nhau và nằm trong khoảng hợp lệ."""
    parser = argparse.ArgumentParser(description="Đặt thông tin, duyệt trạm và chọn trạm mặc định")
    parser.add_argument("--code", required=True, help="Mã trạm, ví dụ ST001")
    parser.add_argument("--name", help="Tên trạm hiển thị")
    parser.add_argument("--district", help="Khu vực (quận/huyện)")
    parser.add_argument("--lat", type=float, help="Vĩ độ (−90..90)")
    parser.add_argument("--lng", type=float, help="Kinh độ (−180..180)")
    parser.add_argument("--activate", action="store_true", help="Duyệt trạm đang chờ (pending → active)")
    parser.add_argument("--default", action="store_true", help="Đặt làm trạm mặc định (default_station_id)")
    args = parser.parse_args(argv)
    if (args.lat is None) != (args.lng is None):
        parser.error("cần nhập cả --lat và --lng")
    if args.lat is not None and not (-90 <= args.lat <= 90 and -180 <= args.lng <= 180):
        parser.error("tọa độ ngoài khoảng hợp lệ")
    return args


def apply(conn: Connection, args: argparse.Namespace) -> dict:
    """Áp các thay đổi trong một transaction; trả thông tin trạm sau khi sửa. Trạm không tồn tại/đã ngưng → lỗi."""
    code = args.code.upper()
    node = conn.execute(
        text("SELECT id, status FROM nodes WHERE station_code = :code FOR UPDATE"), {"code": code}
    ).one_or_none()
    if node is None:
        raise StationError(f"Không có trạm {code}")
    if node.status == "retired":
        raise StationError(f"Trạm {code} đã ngưng hoạt động")

    params = {"id": node.id, "name": args.name, "district": args.district, "lat": args.lat, "lng": args.lng}
    conn.execute(
        text(
            "UPDATE nodes SET name = COALESCE(:name, name), district = COALESCE(:district, district), "
            "geom = CASE WHEN CAST(:lat AS double precision) IS NULL THEN geom "
            "ELSE ST_SetSRID(ST_MakePoint(:lng, :lat), 4326) END, "
            "updated_at = now() WHERE id = :id"
        ),
        params,
    )
    if args.activate and node.status == "pending":
        conn.execute(
            text("UPDATE nodes SET status = 'active', approved_at = now(), updated_at = now() WHERE id = :id"),
            {"id": node.id},
        )
    if args.default:
        conn.execute(
            text(
                "INSERT INTO app_settings (key, value) VALUES ('default_station_id', CAST(:value AS jsonb)) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"
            ),
            {"value": json.dumps(code)},
        )
    row = conn.execute(
        text(
            "SELECT station_code, name, district, status, ST_Y(geom) AS lat, ST_X(geom) AS lng "
            "FROM nodes WHERE id = :id"
        ),
        {"id": node.id},
    ).one()
    return dict(row._mapping)


def main(argv: list[str] | None = None) -> int:
    """Chạy script: in thông tin trạm sau khi sửa, hoặc lỗi kèm mã thoát 1."""
    args = parse_args(argv)
    engine = create_engine(get_settings().database_url)
    try:
        with engine.begin() as conn:
            station = apply(conn, args)
    except StationError as e:
        print(f"Lỗi: {e}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print("Đã cập nhật:", station)
    if args.default:
        print(f"Trạm mặc định: {station['station_code']} (backend đọc lại sau tối đa 30 giây)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
