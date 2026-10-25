"""Bảng mức AQI Mỹ (US EPA) dùng chung cho Web và Xiaozhi (backend_design 11.3, U4).

Hằng số trong code, không nằm trong DB: ngưỡng chuẩn US EPA (cùng ngưỡng với `compute_aqi`), màu hiển thị và tông
cảnh báo. Màu lấy theo bảng IQAir đang dùng trên web (quyết định 25/10/2026, thay màu EPA ở §11.3) để giữ giao diện
đã duyệt; chữ (nhãn, khuyến nghị, cảnh báo hiển thị) dịch theo ngôn ngữ ở `core/i18n`.
"""

from dataclasses import dataclass

from app.core.i18n import FALLBACK, t


@dataclass(frozen=True)
class AqiLevel:
    """Một mức AQI: mã cố định, khoảng [min, max], màu nền/nền nhạt/màu chữ và tông của dải cảnh báo hiển thị."""

    key: str
    min: int
    max: int
    color: str  # màu của mức (chấm, thanh, nền số AQI)
    soft: str  # nền nhạt cho thẻ lớn
    text_color: str  # màu chữ đặt trên nền `color`, tương phản ≥ 4,5:1
    tone: str  # ok | info | warning | critical

    def label_in(self, lang: str) -> str:
        """Nhãn của mức theo ngôn ngữ."""
        return t(f"aqi.{self.key}.label", lang)

    def advice_in(self, lang: str) -> str:
        """Khuyến nghị sức khỏe theo ngôn ngữ."""
        return t(f"aqi.{self.key}.advice", lang)

    def alert_in(self, lang: str) -> dict:
        """Cảnh báo hiển thị (không phải cảnh báo Admin/Telegram): suy ra từ mức AQI giờ, không lưu DB."""
        return {
            "tone": self.tone,
            "title": t(f"aqi.{self.key}.alert_title", lang),
            "message": t(f"aqi.{self.key}.alert_message", lang),
        }

    @property
    def label(self) -> str:
        """Nhãn tiếng Việt (API trợ lý luôn dùng tiếng Việt)."""
        return self.label_in(FALLBACK)

    @property
    def advice(self) -> str:
        """Khuyến nghị tiếng Việt."""
        return self.advice_in(FALLBACK)


LEVELS = (
    AqiLevel("good", 0, 50, "#a8e05f", "#eef8e0", "#3f5a1a", "ok"),
    AqiLevel("moderate", 51, 100, "#fdd64b", "#fff7d6", "#6b5310", "info"),
    AqiLevel("usg", 101, 150, "#ff9b57", "#ffeedf", "#5e2606", "warning"),
    AqiLevel("unhealthy", 151, 200, "#fe6a69", "#ffe4e3", "#4e0d10", "warning"),
    AqiLevel("very_unhealthy", 201, 300, "#a97abc", "#f2e9f6", "#2a1033", "critical"),
    AqiLevel("hazardous", 301, 500, "#a87383", "#f3e6ea", "#26080f", "critical"),
)


def level_of(aqi: int | None) -> AqiLevel | None:
    """Mức chứa giá trị `aqi`; trên 500 xếp vào "Nguy hiểm"; không có AQI thì None."""
    if aqi is None:
        return None
    return next((level for level in LEVELS if aqi <= level.max), LEVELS[-1])


def scale(lang: str) -> list[dict]:
    """Bảng 6 mức cho `/public/aqi-scale`: khoảng, mã, màu, nhãn, khuyến nghị và cảnh báo hiển thị theo ngôn ngữ."""
    return [
        {
            "level": lv.key,
            "min": lv.min,
            "max": lv.max,
            "color": lv.color,
            "soft": lv.soft,
            "text_color": lv.text_color,
            "label": lv.label_in(lang),
            "advice": lv.advice_in(lang),
            "alert": lv.alert_in(lang),
        }
        for lv in LEVELS
    ]
