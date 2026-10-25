"""i18n vi/en và bảng mức AQI hiển thị (backend_design 11.1, 11.3, 18 "Ngôn ngữ", "Màu và cảnh báo theo mức AQI")."""

import json
import re
from pathlib import Path

import pytest

from app.core import aqi_scale
from app.core.i18n import _DIR, pick_language, t

FRONTEND_AQI = Path(__file__).resolve().parents[3] / "frontend" / "src" / "lib" / "aqi.ts"


def _keys(node: dict, prefix: str = "") -> set[str]:
    """Mọi khóa lá của một file chuỗi, dạng "aqi.good.label"."""
    out = set()
    for k, v in node.items():
        out |= _keys(v, f"{prefix}{k}.") if isinstance(v, dict) else {prefix + k}
    return out


def test_vi_and_en_have_same_keys():
    vi = json.loads((_DIR / "vi.json").read_text(encoding="utf-8"))
    en = json.loads((_DIR / "en.json").read_text(encoding="utf-8"))
    assert _keys(vi) == _keys(en)


@pytest.mark.parametrize(
    ("query", "header", "expected"),
    [
        ("en", "vi", "en"),  # ?lang= ghi đè header
        (None, "en-US,en;q=0.9,vi;q=0.8", "en"),
        (None, "fr-FR, vi;q=0.4, en;q=0.6", "en"),  # theo trọng số q
        (None, "fr", "vi"),  # không hỗ trợ → mặc định
        (None, None, "vi"),
        ("de", "en", "en"),  # ?lang= không hỗ trợ thì bỏ qua
        (None, "en;q=abc, vi", "vi"),  # q sai dạng coi như 0
    ],
)
def test_pick_language(query, header, expected):
    assert pick_language(query, header) == expected


def test_translate_with_params_and_fallback():
    assert t("errors.STATION_NOT_FOUND", "en", code="ST009") == "Station ST009 was not found."
    assert t("errors.STATION_NOT_FOUND", "xx", code="ST009") == "Không tìm thấy trạm ST009."
    assert t("no.such.key", "en") == "no.such.key"


@pytest.mark.parametrize(
    ("aqi", "key"),
    [(50, "good"), (51, "moderate"), (100, "moderate"), (101, "usg"), (150, "usg"), (151, "unhealthy"),
     (200, "unhealthy"), (201, "very_unhealthy"), (300, "very_unhealthy"), (301, "hazardous")],
)  # fmt: skip
def test_level_boundaries(aqi, key):
    """Ranh giới 50/51 … 300/301 ra đúng mức (U4)."""
    assert aqi_scale.level_of(aqi).key == key


def test_scale_has_six_levels_in_both_languages():
    vi, en = aqi_scale.scale("vi"), aqi_scale.scale("en")
    assert [x["level"] for x in vi] == [x["level"] for x in en] == [
        "good", "moderate", "usg", "unhealthy", "very_unhealthy", "hazardous",
    ]  # fmt: skip
    assert [x["alert"]["tone"] for x in vi] == ["ok", "info", "warning", "warning", "critical", "critical"]
    for a, b in zip(vi, en, strict=True):
        assert a["label"] != b["label"] and a["alert"]["title"] and b["alert"]["message"]
        assert (a["color"], a["text_color"], a["min"], a["max"]) == (b["color"], b["text_color"], b["min"], b["max"])
    assert vi[3]["label"] == "Không lành mạnh" and en[3]["label"] == "Unhealthy"


def test_contiguous_ranges():
    levels = aqi_scale.LEVELS
    assert levels[0].min == 0 and levels[-1].max == 500
    assert all(b.min == a.max + 1 for a, b in zip(levels, levels[1:], strict=False))


@pytest.mark.skipif(not FRONTEND_AQI.exists(), reason="không có mã frontend")
def test_palette_matches_frontend():
    """Màu dùng bảng IQAir đang hiển thị trên web (quyết định 25/10/2026), backend là nguồn cho frontend."""
    src = FRONTEND_AQI.read_text(encoding="utf-8")
    frontend = re.findall(r'color: "(#[0-9a-f]{6})",\s*soft: "(#[0-9a-f]{6})",\s*text: "(#[0-9a-f]{6})"', src)
    assert frontend == [(lv.color, lv.soft, lv.text_color) for lv in aqi_scale.LEVELS]
