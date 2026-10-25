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

from app.core import settings_store, timeutil
from app.core.aqi_scale import level_of
from app.modules.devices import service as devices
from app.modules.devices.models import Node
from app.modules.hourly import service as hourly
from app.modules.hourly.aggregate import aqi_from_pm
from app.modules.hourly.models import NodeHourly
from app.modules.stations.schemas import (
    UNITS,
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
            coverage=_r2(h.coverage),
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


# ---------- chuỗi thời gian, chu kỳ ngày, xếp hạng (backend_design 11.3–11.4) ----------

SERIES_METRICS = ("aqi", "pm25", "pm10", "temperature", "humidity", "co2", "tvoc")
DEFAULT_SERIES_METRICS = ("aqi", "pm25", "pm10", "temperature", "humidity")
MAX_RANGE = {
    "raw": timedelta(days=2),
    "5min": timedelta(days=7),
    "hour": timedelta(days=90),
    "day": timedelta(days=730),
}
RAW_POINT_LIMIT = 20_000
_INT_METRICS = ("aqi", "co2", "tvoc")


class RangeTooLarge(Exception):
    """Khoảng thời gian vượt giới hạn của độ phân giải (422 RANGE_TOO_LARGE)."""

    def __init__(self, resolution: str):
        super().__init__(resolution)
        self.resolution = resolution
        self.max_days = MAX_RANGE[resolution].days


async def series(
    session: AsyncSession, node: Node, metrics: list[str], start: datetime, end: datetime, resolution: str
) -> dict:
    """Chuỗi thời gian dạng cột trong (start, end]. Mốc không có dữ liệu trả null (biểu đồ để khoảng đứt).

    raw: số đo thô tin cậy (AQI tức thời); 5min: trung bình 5 phút (AQI từ PM trung bình); hour: `node_hourly`
    (nhãn h = cửa sổ (h−1, h], kèm `n_samples`, `coverage`); day: trung bình ngày theo giờ Việt Nam.
    """
    if end - start > MAX_RANGE[resolution]:
        raise RangeTooLarge(resolution)
    out: dict = {"station_id": node.station_code, "resolution": resolution, "from": start, "to": end}
    if resolution == "raw":
        rows = await telemetry.public_raw(session, node.id, start, end, RAW_POINT_LIMIT)
        out["time"] = [r.measured_at for r in rows]
        values = {m: [getattr(r, "aqi_instant" if m == "aqi" else m) for r in rows] for m in metrics}
    elif resolution == "5min":
        step = timedelta(minutes=5)
        by_time = {r.bucket_end: r for r in await telemetry.bucket_means(session, node.id, start, end, 5)}
        out["time"] = _grid(start, end, step)
        values = _columns(out["time"], by_time, metrics, aqi=lambda r: aqi_from_pm(r.pm25, r.pm10))
    elif resolution == "hour":
        by_time = {r.hour_end: r for r in await hourly.series_hour(session, node.id, start, end)}
        out["time"] = _grid(start, end, timedelta(hours=1))
        values = _columns(out["time"], by_time, metrics, aqi=lambda r: r.aqi, suffix="_avg")
        out["n_samples"] = [by_time[t].n_samples if t in by_time else 0 for t in out["time"]]
        out["coverage"] = [_r2(by_time[t].coverage) if t in by_time else None for t in out["time"]]
    else:
        by_day = {d.day: d for d in await hourly.series_day(session, node.id, start, end)}
        out["time"] = _days(start, end)
        values = _columns(out["time"], by_day, metrics, aqi=lambda d: d.aqi)
        out["n_hours"] = [by_day[d].n_hours if d in by_day else 0 for d in out["time"]]
    for m in metrics:
        out[m] = [_metric_value(m, v) for v in values[m]]
    out["units"] = {k: v for k, v in UNITS.items() if k in metrics}
    return out


async def profile_of(session: AsyncSession, node: Node, days: int, now: datetime) -> list[dict]:
    """Chu kỳ ngày: AQI giờ trung bình cho 24 giờ trong ngày (giờ Việt Nam) trong `days` ngày gần nhất."""
    found = {p.hour_of_day: p for p in await hourly.profile(session, node.id, now - timedelta(days=days))}
    return [
        {
            "hour_of_day": h,
            "aqi": round(found[h].aqi) if h in found else None,
            "n_hours": found[h].n_hours if h in found else 0,
        }
        for h in range(24)
    ]


async def ranking(session: AsyncSession, metric: str, now: datetime) -> list[dict]:
    """Xếp hạng trạm theo AQI giờ (hoặc PM2.5 giờ) mới nhất, cao trước; trạm mất kết nối hoặc chưa có giờ xếp cuối."""
    stations = await public_stations(session, now)

    def value(s: PublicStation) -> float | None:
        if s.hourly is None:
            return None
        return s.hourly.aqi if metric == "aqi" else s.hourly.pm25_avg

    ranked = sorted(stations, key=lambda s: (s.freshness.is_stale or value(s) is None, -(value(s) or 0)))
    items = []
    for i, s in enumerate(ranked, start=1):
        h = s.hourly
        items.append(
            {
                "rank": i,
                "id": s.node.station_code,
                "name": s.node.name,
                "district": s.node.district,
                "aqi": h.aqi if h else None,
                "level": lv.key if h and (lv := level_of(h.aqi)) else None,
                "pm25": _r(h.pm25_avg) if h else None,
                "hour_end": h.hour_end if h else None,
                "online": not s.freshness.is_stale,
                "is_simulated": s.node.is_simulated,
            }
        )
    return items


def _grid(start: datetime, end: datetime, step: timedelta) -> list[datetime]:
    """Các nhãn cuối khung cách đều `step` nằm trong (start, end]."""
    epoch = datetime(1970, 1, 1, tzinfo=start.tzinfo)
    first = start - (start - epoch) % step + step
    last = end - (end - epoch) % step
    return [first + i * step for i in range(int((last - first) / step) + 1)] if first <= last else []


def _days(start: datetime, end: datetime) -> list:
    """Các ngày (giờ Việt Nam) có giờ thuộc (start, end]; ngày của giờ h là ngày của h − 1 giờ."""
    first = timeutil.to_local(start).date()
    last = timeutil.to_local(end - timedelta(hours=1)).date()
    return [first + timedelta(days=i) for i in range((last - first).days + 1)] if first <= last else []


def _columns(times: list, by_time: dict, metrics: list[str], *, aqi, suffix: str = "") -> dict[str, list]:
    """Giá trị từng chỉ số theo đúng lưới thời gian; mốc không có dữ liệu → None."""
    out = {}
    for m in metrics:
        if m == "aqi":
            out[m] = [aqi(by_time[t]) if t in by_time else None for t in times]
        else:
            out[m] = [getattr(by_time[t], f"{m}{suffix}") if t in by_time else None for t in times]
    return out


def _metric_value(metric: str, value: float | None) -> float | int | None:
    """AQI, CO2, TVOC là số nguyên; còn lại 1 chữ số thập phân; null giữ null."""
    if value is None:
        return None
    return round(value) if metric in _INT_METRICS else round(value, 1)


def _r2(value: float | None) -> float | None:
    return None if value is None else round(value, 2)
