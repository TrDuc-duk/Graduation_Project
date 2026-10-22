"""Nghiệp vụ "trạm" dùng chung cho API trợ lý và API web (backend_modules: stations).

Trạm = node `active` và `is_public`, gọi bằng `station_code` (ST001). Module chỉ đọc, không sở hữu bảng:
lấy node qua `devices`, số đo qua `telemetry`. Cùng trạm, cùng thời điểm thì mọi API trả cùng con số.
"""

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import fmean

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings_store
from app.modules.devices import service as devices
from app.modules.devices.models import Node
from app.modules.telemetry import service as telemetry
from app.modules.telemetry.models import Measurement

DEFAULT_REF = "default"  # người dùng không nêu trạm: dùng trạm mặc định (default_station_id)

# Xu hướng (quyết định 23/10/2026): so trung bình 1/3 thời gian cuối với 1/3 đầu
TREND_THRESHOLD = 10  # chênh ≥ 10 (AQI, hoặc µg/m³ với PM) mới tính là tăng/giảm
MIN_TREND_SAMPLES = 6  # ít hơn thì chưa đủ dữ liệu để nói xu hướng
TREND_METRICS = ("aqi", "pm25", "pm10")
SUMMARY_METRICS = {  # tên chỉ số trên API → cột của chuỗi số đo
    "aqi": "aqi_instant",
    "pm25": "pm25",
    "pm10": "pm10",
    "temperature": "temperature",
    "humidity": "humidity",
}

INCREASING, DECREASING, STABLE, INSUFFICIENT = "increasing", "decreasing", "stable", "insufficient_data"


# ---------- nhận diện trạm ----------


@dataclass(frozen=True)
class Found:
    """Tìm được đúng một trạm."""

    node: Node


@dataclass(frozen=True)
class NotFound:
    """Không trạm công khai nào khớp."""

    ref: str


@dataclass(frozen=True)
class Ambiguous:
    """Nhiều trạm khớp: chatbot cần hỏi lại người dùng."""

    candidates: list[Node]


@dataclass(frozen=True)
class DefaultNotSet:
    """Hỏi trạm mặc định nhưng chưa cấu hình (hoặc trạm đã cấu hình không còn công khai)."""


Resolution = Found | NotFound | Ambiguous | DefaultNotSet


async def list_public(session: AsyncSession) -> list[Node]:
    """Các trạm công khai, theo mã trạm."""
    return await devices.list_public_nodes(session)


async def resolve_ref(session: AsyncSession, ref: str) -> Resolution:
    """Tìm trạm theo `ref`: "default" → trạm mặc định; còn lại khớp mã trạm hoặc tên (xem `match_station`)."""
    stations = await list_public(session)
    if ref.strip().lower() == DEFAULT_REF:
        code = await settings_store.get("default_station_id")
        node = next((s for s in stations if code and s.station_code == str(code).upper()), None)
        return Found(node) if node else DefaultNotSet()
    return match_station(stations, ref)


def match_station(stations: list, ref: str) -> Resolution:
    """Khớp mã trạm (không phân biệt hoa thường), rồi tên bỏ dấu: trùng hẳn trước, sau đó tên có chứa `ref`.

    Không đoán: nhiều trạm cùng khớp thì trả Ambiguous để hỏi lại.
    """
    code = ref.strip().upper()
    by_code = [s for s in stations if s.station_code == code]
    if by_code:
        return Found(by_code[0])
    key = normalize_name(ref)
    if not key:
        return NotFound(ref)
    matches = [s for s in stations if normalize_name(s.name) == key]
    if not matches:
        matches = [s for s in stations if key in normalize_name(s.name)]
    if len(matches) == 1:
        return Found(matches[0])
    return Ambiguous(matches) if matches else NotFound(ref)


def normalize_name(text: str) -> str:
    """Chuẩn hóa tên để so khớp: bỏ dấu tiếng Việt, chữ thường, bỏ chữ "trạm" ở đầu, gộp khoảng trắng.

    "Trạm  Bách Khoa" → "bach khoa".
    """
    decomposed = unicodedata.normalize("NFD", text.replace("đ", "d").replace("Đ", "D"))
    plain = "".join(c for c in decomposed if not unicodedata.combining(c)).lower()
    words = plain.split()
    if words and words[0] == "tram":
        words = words[1:]
    return " ".join(words)


# ---------- độ mới, số đo hiện tại ----------


@dataclass(frozen=True)
class Freshness:
    """Độ mới của số đo gần nhất, tính theo thời điểm server NHẬN dữ liệu."""

    last_received_at: datetime | None
    age_s: int | None
    stale_after_s: int
    is_stale: bool  # quá stale_after_s chưa nhận số đo mới (hoặc chưa có số đo nào)


async def freshness(node: Node, latest: Measurement | None, now: datetime) -> Freshness:
    """Dữ liệu cũ khi quá offline_after_s của node (chưa đặt thì default_node_offline_after_s) chưa có số đo mới."""
    stale_after = node.offline_after_s or await settings_store.get("default_node_offline_after_s")
    if latest is None:
        return Freshness(last_received_at=None, age_s=None, stale_after_s=stale_after, is_stale=True)
    age = int((now - latest.received_at).total_seconds())
    return Freshness(
        last_received_at=latest.received_at, age_s=age, stale_after_s=stale_after, is_stale=age > stale_after
    )


async def latest_trusted(session: AsyncSession, node_id: int) -> Measurement | None:
    """Số đo "hiện tại" của trạm: mới nhất trong các số đo không bị cách ly, không nghi cũ, không bị thay thế."""
    return await telemetry.latest_trusted_reading(session, node_id)


# ---------- tóm tắt lịch sử ----------


@dataclass(frozen=True)
class MetricSummary:
    """Trung bình, thấp nhất, cao nhất, số giá trị và xu hướng của một chỉ số; không có giá trị thì null."""

    avg: float | None
    min: float | None
    max: float | None
    n: int
    trend: str | None  # chỉ với AQI, PM2.5, PM10


@dataclass(frozen=True)
class Summary:
    """Tóm tắt các số đo dùng được trong khoảng yêu cầu; `first_at`/`last_at` là khoảng thực tế có dữ liệu."""

    since: datetime
    first_at: datetime | None
    last_at: datetime | None
    n_samples: int
    metrics: dict[str, MetricSummary]


async def summary(session: AsyncSession, node_id: int, hours: int, now: datetime) -> Summary:
    """Tóm tắt `hours` giờ gần nhất của trạm (không trả cả chuỗi số đo)."""
    since = now - timedelta(hours=hours)
    return summarize(await telemetry.trusted_series(session, node_id, since), since)


def summarize(rows: list, since: datetime) -> Summary:
    """Tóm tắt các dòng (measured_at, aqi_instant, pm25, …) đã xếp cũ → mới; giá trị null bị bỏ qua."""
    metrics = {}
    for name, column in SUMMARY_METRICS.items():
        points = [(r.measured_at, getattr(r, column)) for r in rows if getattr(r, column) is not None]
        values = [v for _, v in points]
        metrics[name] = MetricSummary(
            avg=round(fmean(values), 1) if values else None,
            min=min(values) if values else None,
            max=max(values) if values else None,
            n=len(values),
            trend=trend(points) if name in TREND_METRICS else None,
        )
    return Summary(
        since=since,
        first_at=rows[0].measured_at if rows else None,
        last_at=rows[-1].measured_at if rows else None,
        n_samples=len(rows),
        metrics=metrics,
    )


def trend(points: list[tuple[datetime, float]]) -> str:
    """Xu hướng của chuỗi (thời điểm, giá trị) đã xếp theo thời gian: so trung bình 1/3 thời gian cuối với 1/3 đầu.

    Chênh ≥ TREND_THRESHOLD là tăng/giảm, còn lại ổn định; dưới MIN_TREND_SAMPLES giá trị thì chưa đủ dữ liệu.
    """
    if len(points) < MIN_TREND_SAMPLES:
        return INSUFFICIENT
    start, end = points[0][0], points[-1][0]
    third = (end - start) / 3
    if third.total_seconds() <= 0:
        return INSUFFICIENT
    first = [v for t, v in points if t <= start + third]
    last = [v for t, v in points if t >= end - third]
    diff = fmean(last) - fmean(first)
    if diff >= TREND_THRESHOLD:
        return INCREASING
    if diff <= -TREND_THRESHOLD:
        return DECREASING
    return STABLE
