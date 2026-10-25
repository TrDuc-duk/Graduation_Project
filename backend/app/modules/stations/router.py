"""API công khai `/api/v1/public/*` (backend_design 11.3): chỉ đọc, không đăng nhập, theo ngôn ngữ của request.

Route tĩnh (`stations.geojson`, `stations/nearest`) khai báo trước `stations/{code}` để không bị nhận nhầm là mã trạm.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import aqi_scale, ratelimit, security_events, timeutil
from app.core.db import run_in_transaction
from app.core.errors import AppError
from app.core.i18n import language, pick_language, t
from app.core.ratelimit import client_ip
from app.modules.stations import service
from app.modules.stations.schemas import (
    AqiScaleOut,
    NearestItem,
    NearestOut,
    OverviewOut,
    StationDetailOut,
    StationsOut,
)

PUBLIC_LIMIT_PER_MIN = 120  # backend_design 14.2: API công khai theo IP


async def rate_limit(request: Request) -> None:
    """Giới hạn 120 request/phút mỗi IP; vượt → 429 và ghi security_events."""
    ip = client_ip(request)
    if not await ratelimit.hit(f"public:ip:{ip}", PUBLIC_LIMIT_PER_MIN):
        await security_events.record_now("rate_limited", "warning", source_ip=ip, scope="public")
        lang = pick_language(request.query_params.get("lang"), request.headers.get("accept-language"))
        raise AppError("RATE_LIMITED", 429, t("errors.RATE_LIMITED", lang))


router = APIRouter(prefix="/public", tags=["public"], dependencies=[Depends(rate_limit)])

Lang = Annotated[str, Depends(language)]


@router.get("/overview", response_model=OverviewOut)
async def overview(_: Lang) -> OverviewOut:
    """Tổng quan: số trạm, AQI giờ trung bình, trạm ô nhiễm nhất, trạm mặc định khi không có vị trí."""
    return await run_in_transaction(lambda s: service.overview(s, timeutil.now()))


@router.get("/stations", response_model=StationsOut)
async def stations(_: Lang) -> StationsOut:
    """Danh sách trạm công khai kèm số đo mới nhất và AQI giờ (bản đồ, danh sách)."""
    now = timeutil.now()
    found = await run_in_transaction(lambda s: service.public_stations(s, now))
    return StationsOut(items=[service.to_station_out(st, now) for st in found])


@router.get("/stations.geojson")
async def stations_geojson(_: Lang) -> dict:
    """Như danh sách, dạng GeoJSON FeatureCollection."""
    return await run_in_transaction(lambda s: service.geojson(s, timeutil.now()))


@router.get("/stations/nearest", response_model=NearestOut)
async def nearest(
    _: Lang,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
    limit: Annotated[int, Query(ge=1, le=10)] = 3,
) -> NearestOut:
    """Trạm gần vị trí người dùng nhất, kèm khoảng cách mét (tọa độ người dùng không được lưu)."""
    now = timeutil.now()
    found = await run_in_transaction(lambda s: service.nearest(s, lat, lng, limit, now))
    return NearestOut(
        items=[NearestItem(**service.to_station_out(st, now).model_dump(), distance_m=round(d)) for st, d in found]
    )


@router.get("/aqi-scale", response_model=AqiScaleOut)
async def scale(lang: Lang) -> AqiScaleOut:
    """Bảng 6 mức AQI: khoảng, mã, màu, nhãn, khuyến nghị, cảnh báo hiển thị (nguồn chung cho Web và Xiaozhi)."""
    return AqiScaleOut(items=aqi_scale.scale(lang))


@router.get("/ranking")
async def ranking(lang: Lang, metric: Literal["aqi", "pm25"] = "aqi") -> dict:
    """Xếp hạng trạm theo AQI giờ mới nhất (cao trước); trạm mất kết nối hoặc chưa có AQI giờ xếp cuối."""
    items = await run_in_transaction(lambda s: service.ranking(s, metric, timeutil.now()))
    return {"metric": metric, "items": [{**i, "hour_end": _iso(i["hour_end"])} for i in items]}


@router.get("/stations/{code}/series")
async def series(
    code: Annotated[str, Path(max_length=16)],
    lang: Lang,
    metrics: Annotated[str, Query(max_length=100)] = ",".join(service.DEFAULT_SERIES_METRICS),
    from_: Annotated[datetime | None, Query(alias="from")] = None,
    to: datetime | None = None,
    resolution: Literal["raw", "5min", "hour", "day"] = "hour",
) -> dict:
    """Chuỗi thời gian dạng cột (backend_design 11.4); mặc định 24 giờ gần nhất theo giờ. Quá giới hạn → 422."""
    wanted = [m.strip() for m in metrics.split(",") if m.strip()]
    if not wanted or any(m not in service.SERIES_METRICS for m in wanted) or len(set(wanted)) != len(wanted):
        raise AppError(
            "INVALID_PARAMS", 422, t("errors.INVALID_PARAMS", lang), {"metrics": list(service.SERIES_METRICS)}
        )
    end = _utc(to) if to else timeutil.now()
    start = _utc(from_) if from_ else end - timedelta(hours=24)
    if start >= end:
        raise AppError("INVALID_PARAMS", 422, t("errors.INVALID_PARAMS", lang), {"from": "phải trước to"})

    async def work(session: AsyncSession) -> dict | None:
        found = await service.public_station(session, code, timeutil.now())
        return None if found is None else await service.series(session, found.node, wanted, start, end, resolution)

    try:
        out = await run_in_transaction(work)
    except service.RangeTooLarge as exc:
        params = {"resolution": exc.resolution, "max_days": exc.max_days}
        raise AppError("RANGE_TOO_LARGE", 422, t("errors.RANGE_TOO_LARGE", lang, **params), params) from None
    if out is None:
        raise AppError("STATION_NOT_FOUND", 404, t("errors.STATION_NOT_FOUND", lang, code=code))
    return {**out, "from": _iso(out["from"]), "to": _iso(out["to"]), "time": [_iso(x) for x in out["time"]]}


@router.get("/stations/{code}/profile")
async def profile(
    code: Annotated[str, Path(max_length=16)], lang: Lang, days: Annotated[int, Query(ge=1, le=90)] = 30
) -> dict:
    """Chu kỳ ngày: AQI giờ trung bình theo giờ trong ngày của `days` ngày gần nhất."""
    now = timeutil.now()

    async def work(session: AsyncSession) -> list | None:
        found = await service.public_station(session, code, now)
        return None if found is None else await service.profile_of(session, found.node, days, now)

    items = await run_in_transaction(work)
    if items is None:
        raise AppError("STATION_NOT_FOUND", 404, t("errors.STATION_NOT_FOUND", lang, code=code))
    return {"station_id": code.strip().upper(), "days": days, "items": items}


@router.get("/stations/{code}", response_model=StationDetailOut)
async def station(code: Annotated[str, Path(max_length=16)], lang: Lang) -> StationDetailOut:
    """Chi tiết trạm: số đo mới nhất, AQI giờ, độ mới dữ liệu. Không tồn tại hoặc không công khai → 404."""
    now = timeutil.now()
    found = await run_in_transaction(lambda s: service.public_station(s, code, now))
    if found is None:
        raise AppError("STATION_NOT_FOUND", 404, t("errors.STATION_NOT_FOUND", lang, code=code))
    return service.to_detail_out(found, now)


def _utc(t: datetime) -> datetime:
    """Đổi thời điểm sang UTC; không có múi giờ thì hiểu là giờ Việt Nam."""
    return (t if t.tzinfo else t.replace(tzinfo=timeutil.LOCAL_TZ)).astimezone(UTC)


def _iso(value: datetime | date | None) -> str | None:
    """Thời điểm → ISO +07:00; ngày → YYYY-MM-DD."""
    if value is None:
        return None
    return timeutil.iso_local(value) if isinstance(value, datetime) else value.isoformat()
