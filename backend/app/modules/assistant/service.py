"""Nghiệp vụ API trợ lý: dùng lại `stations` (cùng số liệu với web), thêm câu tóm tắt tiếng Việt cho chatbot.

Chatbot chỉ diễn đạt: số liệu, mức AQI, khuyến nghị và câu `summary_vi` đều do backend tạo ở đây.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings_store, timeutil
from app.core.aqi_scale import level_of
from app.core.errors import AssistantError
from app.core.i18n import t
from app.modules.assistant.schemas import (
    UNITS,
    CurrentOut,
    ForecastBodyOut,
    ForecastItemOut,
    ForecastOut,
    MetricOut,
    StationItem,
    StationRef,
    StationsOut,
    SummaryOut,
)
from app.modules.devices.models import Node
from app.modules.stations import service as stations

MAX_SUMMARY_HOURS = 72
DEFAULT_SUMMARY_HOURS = 24
DEFAULT_HORIZONS = [3, 6, 12, 24]
TREND_LABELS = {
    stations.INCREASING: "tăng",
    stations.DECREASING: "giảm",
    stations.STABLE: "ổn định",
    stations.INSUFFICIENT: "chưa đủ dữ liệu để đánh giá",
}
FORECAST_UNAVAILABLE = "Chưa có dự báo cho trạm này."


@dataclass
class CallContext:
    """Thông tin một lần gọi để ghi nhật ký assistant_calls; trạm được điền sau khi nhận diện."""

    tool: str
    params: dict = field(default_factory=dict)
    station_code: str | None = None
    node_id: int | None = None


# ---------- các tool ----------


async def list_stations(session: AsyncSession, ctx: CallContext) -> StationsOut:
    """Danh sách trạm công khai kèm trạm mặc định và trạm nào đang gửi dữ liệu."""
    now = timeutil.now()
    items = []
    for node in await stations.list_public(session):
        latest = await stations.latest_trusted(session, node.id)
        fresh = await stations.freshness(node, latest, now)
        items.append(
            StationItem(
                **_ref(node).model_dump(),
                online=not fresh.is_stale,
                last_measured_at=_local(latest.measured_at) if latest else None,
            )
        )
    default = await settings_store.get("default_station_id")
    default_code = str(default).upper() if default and any(s.code == str(default).upper() for s in items) else None
    return StationsOut(stations=items, default_station=default_code, summary_vi=_stations_text(items, default_code))


async def current(session: AsyncSession, ref: str, ctx: CallContext) -> CurrentOut:
    """Chất lượng không khí hiện tại của trạm `ref` (mã, tên hoặc "default")."""
    node = await _resolve(session, ref, ctx)
    latest = await stations.latest_trusted(session, node.id)
    if latest is None:
        raise AssistantError(
            "NO_DATA", 404, f"Trạm {node.name} ({node.station_code}) chưa có số đo nào.", station=_ref(node)
        )
    now = timeutil.now()
    fresh = await stations.freshness(node, latest, now)
    hour = await stations.current_hourly(session, node.id, now)
    aqi = hour.aqi if hour else None
    level = level_of(aqi)
    out = CurrentOut(
        station=_ref(node),
        aqi=aqi,
        aqi_kind="hourly",
        aqi_hour_end=_local(hour.hour_end) if hour else None,
        hourly_aqi=aqi,
        aqi_instant=latest.aqi_instant,
        level=level.key if level else None,
        level_label=level.label if level else None,
        advice=level.advice if level else None,
        pm25=latest.pm25,
        pm10=latest.pm10,
        temperature=latest.temperature,
        humidity=latest.humidity,
        units=UNITS,
        measured_at=_local(latest.measured_at),
        age_minutes=max(0, int((now - latest.measured_at).total_seconds() // 60)),
        stale=fresh.is_stale,
        last_updated_at=_local(fresh.last_received_at) if fresh.last_received_at else None,
        summary_vi="",
    )
    return out.model_copy(update={"summary_vi": current_text(out)})


async def history_summary(session: AsyncSession, ref: str, hours_raw: str | None, ctx: CallContext) -> SummaryOut:
    """Thống kê `hours` giờ gần nhất (1–72, mặc định 24) của trạm: trung bình, thấp nhất, cao nhất, xu hướng."""
    hours = parse_hours(hours_raw)
    node = await _resolve(session, ref, ctx)
    s = await stations.summary(session, node.id, hours, timeutil.now())
    if s.n_samples == 0:
        latest = await stations.latest_trusted(session, node.id)
        last = f" Số đo gần nhất lúc {say_time(latest.measured_at)}." if latest else " Trạm chưa có số đo nào."
        raise AssistantError(
            "NO_DATA",
            404,
            f"Trạm {node.name} ({node.station_code}) không có số đo trong {hours} giờ qua.{last}",
            station=_ref(node),
            last_measured_at=_local(latest.measured_at) if latest else None,
        )
    metrics = {
        name: MetricOut(
            avg=m.avg,
            min=m.min,
            max=m.max,
            n=m.n,
            trend=m.trend,
            trend_label=TREND_LABELS[m.trend] if m.trend else None,
        )
        for name, m in s.metrics.items()
    }
    out = SummaryOut(
        station=_ref(node),
        hours=hours,
        requested_from=_local(s.since),
        data_from=_local(s.first_at),
        data_to=_local(s.last_at),
        n_samples=s.n_samples,
        metrics=metrics,
        aqi_kind="instant",
        units=UNITS,
        summary_vi="",
    )
    return out.model_copy(update={"summary_vi": summary_text(out)})


async def forecast(session: AsyncSession, ref: str, horizons_raw: str | None, ctx: CallContext) -> ForecastOut:
    """Dự báo đã lưu của trạm tại các mốc hỏi (mặc định 3, 6, 12, 24 giờ), cùng quy tắc với web (R23)."""
    horizons = parse_horizons(horizons_raw)
    node = await _resolve(session, ref, ctx)
    cf = await stations.station_forecast(session, node, timeutil.now(), horizons)
    body = None
    if cf.forecast is not None:
        pub = cf.forecast
        body = ForecastBodyOut(
            model_version=pub.model_version,
            input_hour=_local(pub.input_hour),
            issued_at=_local(pub.issued_at),
            issue_kind=pub.issue_kind,
            items=[
                ForecastItemOut(
                    horizon_h=i.horizon_h,
                    target_time=_local(i.target_time),
                    aqi=i.aqi,
                    level=i.level,
                    level_label=lv.label if (lv := level_of(i.aqi)) else None,
                    confidence=i.confidence,
                    typical_error=i.typical_error,
                )
                for i in pub.items
            ],
        )
    message = t(cf.message_key, "vi", **cf.message_params) if cf.message_key else None
    out = ForecastOut(
        station=_ref(node), status=cf.status, horizons=horizons, age_hours=cf.age_hours, forecast=body,
        message_vi=message, summary_vi="",
    )  # fmt: skip
    return out.model_copy(update={"summary_vi": forecast_text(out)})


# ---------- nhận diện trạm, kiểm tra tham số ----------


async def _resolve(session: AsyncSession, ref: str, ctx: CallContext) -> Node:
    """Trạm theo `ref`; không tìm được, nhiều trạm khớp hoặc chưa đặt trạm mặc định → lỗi kèm danh sách để hỏi lại."""
    found = await stations.resolve_ref(session, ref)
    if isinstance(found, stations.Found):
        ctx.station_code, ctx.node_id = found.node.station_code, found.node.id
        return found.node
    public = [_ref(n) for n in await stations.list_public(session)]
    names = _list_text(public)
    if isinstance(found, stations.Ambiguous):
        candidates = [_ref(n) for n in found.candidates]
        listed = ", ".join(f"{r.code} {r.name}" for r in candidates)
        message = f"Có {len(candidates)} trạm khớp với '{ref}': {listed}. Hãy hỏi người dùng muốn xem trạm nào."
        raise AssistantError("STATION_AMBIGUOUS", 409, message, candidates=candidates)
    if isinstance(found, stations.DefaultNotSet):
        raise AssistantError(
            "DEFAULT_STATION_NOT_SET",
            404,
            f"Chưa cấu hình trạm mặc định. {names} Hãy hỏi người dùng muốn xem trạm nào.",
            stations=public,
        )
    raise AssistantError("STATION_NOT_FOUND", 404, f"Không tìm thấy trạm '{ref}'. {names}", stations=public)


def parse_hours(raw: str | None) -> int:
    """Số giờ cho tóm tắt: số nguyên 1–72; không truyền thì 24."""
    if raw is None or raw.strip() == "":
        return DEFAULT_SUMMARY_HOURS
    try:
        hours = int(raw)
    except ValueError:
        hours = 0
    if not 1 <= hours <= MAX_SUMMARY_HOURS:
        raise AssistantError("INVALID_PARAMS", 422, f"Số giờ phải là số nguyên từ 1 đến {MAX_SUMMARY_HOURS}.")
    return hours


def parse_horizons(raw: str | None) -> list[int]:
    """Mốc dự báo "3,6,12": bội số của 3 trong 3–72 giờ, bỏ trùng, tăng dần; không truyền thì 3, 6, 12, 24."""
    if raw is None or raw.strip() == "":
        return DEFAULT_HORIZONS
    try:
        values = sorted({int(x) for x in raw.split(",") if x.strip()})
    except ValueError:
        values = []
    if not values or any(h % 3 or not 3 <= h <= 72 for h in values):
        raise AssistantError(
            "INVALID_PARAMS", 422, "Mốc dự báo phải là bội số của 3 trong khoảng 3–72 giờ, ví dụ 3,6,12,24."
        )
    return values


# ---------- câu tóm tắt tiếng Việt ----------


def current_text(c: CurrentOut) -> str:
    """Câu tóm tắt số đo hiện tại; dữ liệu cũ thì cảnh báo trước và không đưa khuyến nghị."""
    parts = []
    if c.stale:
        updated = say_time(c.last_updated_at) if c.last_updated_at else "không rõ"
        parts.append(f"Lưu ý: dữ liệu của trạm đã cũ, lần cập nhật cuối lúc {updated}.")
    if c.aqi is not None and c.aqi_hour_end is not None:
        start = say_hour(c.aqi_hour_end - timedelta(hours=1))
        parts.append(
            f"Trạm {c.station.name} ({c.station.code}): AQI giờ {c.aqi}, mức {c.level_label} "
            f"(trung bình từ {start} đến {say_time(c.aqi_hour_end)})."
        )
    else:
        parts.append(f"Trạm {c.station.name} ({c.station.code}) chưa có AQI giờ (cần một giờ dữ liệu đã đóng).")
    instant = f"AQI tức thời {c.aqi_instant}" if c.aqi_instant is not None else "chưa tính được AQI tức thời"
    parts.append(f"Lần đo gần nhất lúc {say_time(c.measured_at)}: {instant}.")
    parts.append(
        f"PM2.5 {say_number(c.pm25, UNITS['pm25'])}, PM10 {say_number(c.pm10, UNITS['pm10'])}, "
        f"nhiệt độ {say_number(c.temperature, UNITS['temperature'])}, "
        f"độ ẩm {say_number(c.humidity, UNITS['humidity'])}."
    )
    if c.advice and not c.stale:
        parts.append(c.advice)
    return " ".join(parts)


def forecast_text(f: ForecastOut) -> str:
    """Câu tóm tắt dự báo: thời điểm tính, từng mốc (mốc độ tin cậy thấp đọc là xu hướng), sai số tham khảo."""
    name = f"{f.station.name} ({f.station.code})"
    if f.forecast is None:
        return f"Trạm {name}: {f.message_vi or FORECAST_UNAVAILABLE} Không có con số dự báo nào để đọc."
    parts = [f.message_vi] if f.message_vi else []
    parts.append(f"Dự báo cho trạm {name} được tính lúc {say_time(f.forecast.issued_at)}.")
    if not f.forecast.items:
        parts.append("Không còn mốc dự báo nào trong tương lai.")
    for i in f.forecast.items:
        trend = " (chỉ là xu hướng, độ tin cậy thấp)" if i.confidence == "low" else ""
        error = f", sai số thường gặp khoảng ±{say_number(i.typical_error, digits=0)}" if i.typical_error else ""
        when = f"Sau {i.horizon_h} giờ, lúc {say_hour(i.target_time)}"
        parts.append(f"{when}: AQI khoảng {i.aqi}, mức {i.level_label}{error}{trend}.")
    return " ".join(parts)


def summary_text(s: SummaryOut) -> str:
    """Câu tóm tắt lịch sử: khoảng có dữ liệu, rồi AQI, PM2.5, PM10 (kèm xu hướng), nhiệt độ, độ ẩm."""
    parts = [
        f"Trong {s.hours} giờ qua, trạm {s.station.name} ({s.station.code}) có {s.n_samples} số đo, "
        f"từ {say_time(s.data_from)} đến {say_time(s.data_to)}."
    ]
    for name, label, unit, digits in (
        ("aqi", "AQI tức thời", "", 0),
        ("pm25", "PM2.5", UNITS["pm25"], 1),
        ("pm10", "PM10", UNITS["pm10"], 1),
    ):
        m = s.metrics[name]
        if m.avg is None:
            parts.append(f"{label}: không có số đo.")
            continue
        parts.append(
            f"{label} trung bình {say_number(m.avg, unit, digits)}, thấp nhất {say_number(m.min, unit, digits)}, "
            f"cao nhất {say_number(m.max, unit, digits)}, xu hướng {m.trend_label}."
        )
    t, h = s.metrics["temperature"], s.metrics["humidity"]
    parts.append(
        f"Nhiệt độ trung bình {say_number(t.avg, UNITS['temperature'])}, "
        f"độ ẩm trung bình {say_number(h.avg, UNITS['humidity'])}."
    )
    return " ".join(parts)


def say_number(value: float | None, unit: str = "", digits: int = 1) -> str:
    """Số kiểu Việt Nam (dấu phẩy thập phân) kèm đơn vị; null → "không có số đo"."""
    if value is None:
        return "không có số đo"
    text = f"{value:.{digits}f}".replace(".", ",")
    return f"{text} {unit}" if unit else text


def say_hour(t: datetime) -> str:
    """Giờ dạng đọc: "13:00"."""
    return timeutil.to_local(t).strftime("%H:%M")


def say_time(t: datetime) -> str:
    """Thời điểm theo giờ Việt Nam: "14:05 ngày 16/10"."""
    local = timeutil.to_local(t)
    return f"{local:%H:%M} ngày {local:%d/%m}"


def _stations_text(items: list[StationItem], default_code: str | None) -> str:
    """Câu tóm tắt danh sách trạm."""
    if not items:
        return "Hiện chưa có trạm quan trắc nào được công khai."
    status = [f"{s.code} {s.name} ({'đang gửi dữ liệu' if s.online else 'không gửi dữ liệu mới'})" for s in items]
    default = f" Trạm mặc định là {default_code}." if default_code else " Chưa cấu hình trạm mặc định."
    return f"Có {len(items)} trạm: " + "; ".join(status) + "." + default


def _list_text(refs: list[StationRef]) -> str:
    """ "Các trạm hiện có: ST001 Bách Khoa, ST002 Đống Đa." hoặc báo chưa có trạm."""
    if not refs:
        return "Hiện chưa có trạm quan trắc nào được công khai."
    return "Các trạm hiện có: " + ", ".join(f"{r.code} {r.name}" for r in refs) + "."


def _ref(node: Node) -> StationRef:
    """Thông tin trạm công khai của một node."""
    return StationRef(code=node.station_code, name=node.name, district=node.district)


def _local(t: datetime) -> datetime:
    """Thời điểm trả về API: giờ Việt Nam (+07:00), làm tròn tới giây cho chatbot dễ đọc."""
    return timeutil.to_local(t).replace(microsecond=0)
