"""API công khai `/api/v1/public/*` (backend_design 11.3): chỉ đọc, không đăng nhập, theo ngôn ngữ của request.

Route tĩnh (`stations.geojson`, `stations/nearest`) khai báo trước `stations/{code}` để không bị nhận nhầm là mã trạm.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.core import aqi_scale, timeutil
from app.core.db import run_in_transaction
from app.core.errors import AppError
from app.core.i18n import language, t
from app.modules.stations import service
from app.modules.stations.schemas import (
    AqiScaleOut,
    NearestItem,
    NearestOut,
    OverviewOut,
    StationDetailOut,
    StationsOut,
)

router = APIRouter(prefix="/public", tags=["public"])

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


@router.get("/stations/{code}", response_model=StationDetailOut)
async def station(code: Annotated[str, Path(max_length=16)], lang: Lang) -> StationDetailOut:
    """Chi tiết trạm: số đo mới nhất, AQI giờ, độ mới dữ liệu. Không tồn tại hoặc không công khai → 404."""
    now = timeutil.now()
    found = await run_in_transaction(lambda s: service.public_station(s, code, now))
    if found is None:
        raise AppError("STATION_NOT_FOUND", 404, t("errors.STATION_NOT_FOUND", lang, code=code))
    return service.to_detail_out(found, now)
