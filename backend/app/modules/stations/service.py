"""Nghiệp vụ "trạm" dùng chung cho API trợ lý và API web (backend_modules: stations).

Trạm = node `active` và `is_public`, gọi bằng `station_code` (ST001); trang công khai còn cần tọa độ (A3).
Module chỉ đọc, không sở hữu bảng: node qua `devices`, số đo qua `telemetry`, AQI giờ qua `hourly`.
Cùng trạm, cùng thời điểm thì mọi API trả cùng con số.
"""

import json
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import fmean

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings_store
from app.core.aqi_scale import level_of
from app.modules.devices import service as devices
from app.modules.devices.models import Node
from app.modules.hourly import service as hourly
from app.modules.hourly.models import NodeHourly
from app.modules.stations.schemas import (
    FreshnessOut,
    HourlyOut,
    LatestOut,
    MostPolluted,
    OverviewOut,
    StationDetailOut,
    StationOut,
)
from app.modules.telemetry import service as telemetry
from app.modules.telemetry.models import Measurement
from app.modules.telemetry.qc import QcFlag

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


# ---------- API công khai /public/* (backend_design 11.3) ----------

HOURLY_FRESH = timedelta(hours=2)  # AQI giờ "hiện hành" = giờ đã đóng gần nhất, không cũ hơn 2 giờ


@dataclass(frozen=True)
class PublicStation:
    """Trạm công khai (active, is_public, có tọa độ) kèm số đo tin cậy mới nhất, độ mới và AQI giờ hiện hành."""

    node: Node
    lat: float
    lng: float
    latest: Measurement | None
    freshness: Freshness
    hourly: NodeHourly | None


async def public_stations(session: AsyncSession, now: datetime) -> list[PublicStation]:
    """Mọi trạm công khai có tọa độ, theo mã trạm. Trạm chưa có tọa độ không hiện trên trang công khai (A3)."""
    return [await _public(session, r.Node, r.lat, r.lng, now) for r in await devices.public_points(session)]


async def public_station(session: AsyncSession, code: str, now: datetime) -> PublicStation | None:
    """Một trạm công khai theo mã (không phân biệt hoa thường); không có hoặc không công khai → None."""
    code = code.strip().upper()
    row = next((r for r in await devices.public_points(session) if r.Node.station_code == code), None)
    return await _public(session, row.Node, row.lat, row.lng, now) if row else None


async def nearest(
    session: AsyncSession, lat: float, lng: float, limit: int, now: datetime
) -> list[tuple[PublicStation, float]]:
    """Trạm công khai gần (lat, lng) nhất kèm khoảng cách mét."""
    rows = await devices.nearest_public(session, lat, lng, limit)
    return [(await _public(session, r.Node, r.lat, r.lng, now), r.distance_m) for r in rows]


async def geojson(session: AsyncSession, now: datetime) -> dict:
    """Trạm công khai dạng GeoJSON FeatureCollection; geometry do PostGIS dựng (`ST_AsGeoJSON`)."""
    features = []
    for r in await devices.public_points(session):
        props = to_station_out(await _public(session, r.Node, r.lat, r.lng, now), now).model_dump(
            mode="json", exclude={"latitude", "longitude"}
        )
        features.append(
            {"type": "Feature", "id": r.Node.station_code, "geometry": json.loads(r.geojson), "properties": props}
        )
    return {"type": "FeatureCollection", "features": features}


async def overview(session: AsyncSession, now: datetime) -> OverviewOut:
    """Tổng quan trang chủ: số trạm, số trạm online, AQI giờ trung bình, trạm ô nhiễm nhất, trạm mặc định."""
    stations = await public_stations(session, now)
    with_aqi = [s for s in stations if s.hourly is not None and s.hourly.aqi is not None]
    worst = max(with_aqi, key=lambda s: s.hourly.aqi, default=None)
    default = await settings_store.get("default_station_id")
    public_codes = {s.node.station_code for s in stations}
    return OverviewOut(
        n_stations=len(stations),
        n_online=sum(1 for s in stations if not s.freshness.is_stale),
        aqi_avg=round(fmean(s.hourly.aqi for s in with_aqi)) if with_aqi else None,
        most_polluted=MostPolluted(
            id=worst.node.station_code, name=worst.node.name, aqi=worst.hourly.aqi, level=level_of(worst.hourly.aqi).key
        )
        if worst
        else None,
        last_updated_at=max((s.latest.measured_at for s in stations if s.latest), default=None),
        default_station_id=str(default).upper() if default and str(default).upper() in public_codes else None,
    )


def to_station_out(s: PublicStation, now: datetime) -> StationOut:
    """Chuyển trạm sang dạng response công khai (làm tròn, không có trường nhạy cảm)."""
    return StationOut(**_station_fields(s, now))


def to_detail_out(s: PublicStation, now: datetime) -> StationDetailOut:
    """Chi tiết trạm: thêm độ mới dữ liệu và đơn vị."""
    f = s.freshness
    return StationDetailOut(
        **_station_fields(s, now),
        freshness=FreshnessOut(
            last_received_at=f.last_received_at, age_s=f.age_s, stale_after_s=f.stale_after_s, is_stale=f.is_stale
        ),
    )


async def _public(session: AsyncSession, node: Node, lat: float, lng: float, now: datetime) -> PublicStation:
    """Ghép số đo tin cậy mới nhất, độ mới và AQI giờ hiện hành của một trạm."""
    latest = await latest_trusted(session, node.id)
    return PublicStation(
        node=node,
        lat=lat,
        lng=lng,
        latest=latest,
        freshness=await freshness(node, latest, now),
        hourly=await hourly.latest_closed_hour(session, node.id, now - HOURLY_FRESH),
    )


def _station_fields(s: PublicStation, now: datetime) -> dict:
    """Các trường chung của danh sách và chi tiết trạm."""
    n, m, h = s.node, s.latest, s.hourly
    return {
        "id": n.station_code,
        "name": n.name,
        "district": n.district,
        "latitude": s.lat,
        "longitude": s.lng,
        "environment": n.environment,
        "is_simulated": n.is_simulated,
        "online": not s.freshness.is_stale,
        "latest": LatestOut(
            measured_at=m.measured_at,
            time_estimated=bool(m.qc_flags & QcFlag.TIME_ESTIMATED),
            age_minutes=max(0, int((now - m.measured_at).total_seconds() // 60)),
            aqi_instant=m.aqi_instant,
            pm25=_r(m.pm25),
            pm10=_r(m.pm10),
            temperature=_r(m.temperature),
            humidity=_r(m.humidity),
            co2=m.co2,
            tvoc=m.tvoc,
        )
        if m
        else None,
        "hourly": HourlyOut(
            hour_end=h.hour_end,
            aqi=h.aqi,
            level=lv.key if (lv := level_of(h.aqi)) else None,
            dominant=_dominant(h),
            n_samples=h.n_samples,
            coverage=None if h.coverage is None else round(h.coverage, 2),
        )
        if h
        else None,
    }


def _dominant(h: NodeHourly) -> str | None:
    """Chất quyết định AQI giờ: chỉ số phụ lớn hơn (bằng nhau thì PM2.5)."""
    if h.aqi_pm25 is None and h.aqi_pm10 is None:
        return None
    return "pm10" if (h.aqi_pm10 or -1) > (h.aqi_pm25 or -1) else "pm25"


def _r(value: float | None) -> float | None:
    """Làm tròn 1 chữ số thập phân, giữ null."""
    return None if value is None else round(value, 1)
