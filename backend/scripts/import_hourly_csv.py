"""Nạp CSV dạng `dataset.csv` vào một trạm mô phỏng (P10, backend_design 12.4 A10).

    python -m scripts.import_hourly_csv --create "Mô phỏng Hà Nội" --lat 21.03 --lng 105.85 \\
        --csv ../ml/data/dataset.csv --hours 120
    python -m scripts.import_hourly_csv --station ST005 --csv data.csv --end "2026-10-25 10:00"

- CSV đúng 6 cột `time, AQI, pm10, pm2_5, Humidity, Temperature`; giờ Việt Nam, giờ tròn, tăng dần, không trùng.
- Chỉ nạp vào trạm `is_simulated`; trạm thật bị từ chối. Nạp lại cùng dữ liệu không đổi gì.
- Mặc định giữ nguyên nhãn giờ của CSV. `--end` (tùy chọn, ghi rõ) dời cả chuỗi để giờ cuối rơi vào giờ đó,
  ví dụ để trạm mô phỏng có dự báo hiện hành; không bao giờ tự dời ngầm.
- Trạm mô phỏng luôn mang nhãn "Mô phỏng" trên web và trợ lý, không gửi Telegram, không tính vào độ chính xác
  của trạm thật.
"""

import argparse
import asyncio
import math
import sys
from pathlib import Path

import pandas as pd
from src.data_loading import load_raw_dataset

from app.core import timeutil
from app.core.db import get_engine, run_in_transaction
from app.core.timeutil import LOCAL_TZ
from app.modules.devices import service as devices
from app.modules.hourly.service import ImportedHour, import_hours


class CsvImportError(Exception):
    """CSV hoặc tham số không hợp lệ (thông báo in ra cho người chạy)."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Tham số dòng lệnh: chọn trạm có sẵn (--station) hoặc tạo trạm mới (--create, --lat, --lng)."""
    p = argparse.ArgumentParser(description="Nạp CSV dạng dataset.csv vào trạm mô phỏng")
    target = p.add_mutually_exclusive_group(required=True)
    target.add_argument("--station", help="mã trạm mô phỏng đã có, vd ST005")
    target.add_argument("--create", metavar="TÊN", help="tạo trạm mô phỏng mới với tên này")
    p.add_argument("--lat", type=float)
    p.add_argument("--lng", type=float)
    p.add_argument("--district")
    p.add_argument("--csv", type=Path, required=True)
    p.add_argument("--hours", type=int, help="chỉ nạp N giờ cuối của CSV")
    p.add_argument("--end", help="dời chuỗi để giờ cuối là thời điểm này (giờ Việt Nam, giờ tròn)")
    args = p.parse_args(argv)
    if args.create and (args.lat is None or args.lng is None):
        p.error("--create cần --lat và --lng")
    return args


def read_hours(path: Path, last_hours: int | None = None, end: str | None = None) -> list[ImportedHour]:
    """Đọc và kiểm tra CSV; trả các giờ (UTC) theo thứ tự. Sai schema, giờ lẻ, trùng, AQI lạ → CsvImportError."""
    try:
        df = load_raw_dataset(path)  # kiểm tra đúng 6 cột như dataset.csv
    except (ValueError, OSError) as exc:
        raise CsvImportError(str(exc)) from None
    if df.empty:
        raise CsvImportError("CSV không có dòng nào")
    if df["time"].isna().any() or (df["time"] != df["time"].dt.floor("h")).any():
        raise CsvImportError("Cột time phải là giờ tròn (vd 2026-09-22 23:00)")
    if df["time"].duplicated().any() or not df["time"].is_monotonic_increasing:
        raise CsvImportError("Cột time phải tăng dần và không trùng")
    aqi = df["AQI"].dropna()
    if ((aqi % 1) != 0).any() or ((aqi < 0) | (aqi > 500)).any():
        raise CsvImportError("AQI phải là số nguyên trong 0–500")
    for col in ("pm10", "pm2_5"):
        if (df[col].dropna() < 0).any():
            raise CsvImportError(f"{col} không được âm")
    if last_hours:
        df = df.tail(last_hours)
    if end:
        target = pd.Timestamp(end)
        if target != target.floor("h"):
            raise CsvImportError("--end phải là giờ tròn")
        df = df.assign(time=df["time"] + (target - df["time"].iloc[-1]))
    return [
        ImportedHour(
            hour_end=r.time.tz_localize(LOCAL_TZ).tz_convert("UTC").to_pydatetime(),
            aqi=None if _nan(r.AQI) else int(r.AQI),
            pm25=None if _nan(r.pm2_5) else float(r.pm2_5),
            pm10=None if _nan(r.pm10) else float(r.pm10),
            temperature=None if _nan(r.Temperature) else float(r.Temperature),
            humidity=None if _nan(r.Humidity) else float(r.Humidity),
        )
        for r in df.itertuples()
    ]


async def run(args: argparse.Namespace) -> str:
    """Tạo/lấy trạm mô phỏng rồi nạp các giờ trong một transaction; trả dòng tóm tắt."""
    hours = read_hours(args.csv, args.hours, args.end)

    async def work(session):
        if args.create:
            node = await devices.create_simulated_node(session, args.create, args.lat, args.lng, args.district)
        else:
            node = next((n for n in await devices.list_nodes(session) if n.station_code == args.station.upper()), None)
            if node is None:
                raise CsvImportError(f"Không có trạm {args.station}")
        try:
            stats = await import_hours(session, node, hours, timeutil.now())
        except ValueError as exc:
            raise CsvImportError(str(exc)) from None
        return node.station_code, stats

    code, stats = await run_in_transaction(work)
    first, last = timeutil.to_local(hours[0].hour_end), timeutil.to_local(hours[-1].hour_end)
    return (
        f"{code} (mô phỏng): thêm {stats['inserted']}, cập nhật {stats['updated']}, không đổi {stats['unchanged']} "
        f"giờ, từ {first:%Y-%m-%d %H:%M} tới {last:%Y-%m-%d %H:%M} (giờ Việt Nam)."
    )


def _nan(value: float) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


async def _main(argv: list[str] | None) -> int:
    try:
        print(await run(parse_args(argv)))
        return 0
    except CsvImportError as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        return 1
    finally:
        await get_engine().dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(None)))
