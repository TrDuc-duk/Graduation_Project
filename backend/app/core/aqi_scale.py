"""Bảng mức AQI Mỹ (US EPA) dùng chung cho API (backend_design 11.3, U4).

Một nguồn cho nhãn và khuyến nghị: nhãn tiếng Việt khớp `frontend/src/lib/aqi.ts`. Ngưỡng là ngưỡng chuẩn
US EPA, cùng ngưỡng với `compute_aqi` (ml/ml_xgb/src/aqi.py).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AqiLevel:
    """Một mức AQI: mã cố định, khoảng [min, max], nhãn và khuyến nghị sức khỏe tiếng Việt."""

    key: str
    min: int
    max: int
    label: str
    advice: str


LEVELS = (
    AqiLevel("good", 0, 50, "Tốt", "Không khí trong lành, thích hợp cho mọi hoạt động ngoài trời."),
    AqiLevel("moderate", 51, 100, "Trung bình", "Người nhạy cảm nên giảm vận động mạnh ngoài trời."),
    AqiLevel(
        "usg",
        101,
        150,
        "Không tốt cho nhóm nhạy cảm",
        "Nhóm nhạy cảm nên hạn chế ra ngoài và đeo khẩu trang; mọi người nên giảm vận động mạnh ngoài trời.",
    ),
    AqiLevel(
        "unhealthy",
        151,
        200,
        "Không lành mạnh",
        "Mọi người nên tránh vận động mạnh ngoài trời, đóng cửa sổ và đeo khẩu trang lọc bụi khi ra ngoài.",
    ),
    AqiLevel(
        "very_unhealthy",
        201,
        300,
        "Rất không tốt",
        "Mọi người nên tránh hoạt động ngoài trời, đóng kín cửa sổ và bật máy lọc không khí nếu có.",
    ),
    AqiLevel(
        "hazardous",
        301,
        500,
        "Nguy hiểm",
        "Mọi người nên ở trong nhà, tránh mọi hoạt động ngoài trời.",
    ),
)


def level_of(aqi: int | None) -> AqiLevel | None:
    """Mức chứa giá trị `aqi`; trên 500 xếp vào "Nguy hiểm"; không có AQI thì None."""
    if aqi is None:
        return None
    return next((level for level in LEVELS if aqi <= level.max), LEVELS[-1])
