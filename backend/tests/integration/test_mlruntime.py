"""Model registry theo thư mục phiên bản (backend_design 8.1–8.3, 18 "Model registry", "Revision và tái hiện").

Bundle thật ở models/xgb/v1-no_fill (tạo bằng scripts.prepare_model_bundle). Mỗi test dựng MODEL_DIR tạm bằng
hardlink; file cần sửa được ghi thành file mới nên bundle gốc không bao giờ bị đổi.
"""

import hashlib
import json
import os
import shutil
from pathlib import Path

import pandas as pd
import pytest
from src.data_loading import load_raw_dataset
from src.predict import predict as ml_predict

from app.core.config import get_settings
from app.modules.mlruntime import adapter
from app.modules.mlruntime.registry import HORIZONS, BundleInvalid, Registry
from tests.integration.helpers import rows

SOURCE = Path(__file__).resolve().parents[3] / "models" / "xgb" / "v1-no_fill"
pytestmark = pytest.mark.skipif(not SOURCE.is_dir(), reason="chưa có bundle: python -m scripts.prepare_model_bundle")


def link_bundle(dest: Path) -> Path:
    """Dựng một thư mục phiên bản bằng hardlink tới bundle thật (48 file)."""
    dest.mkdir(parents=True)
    for p in SOURCE.glob("xgb_AQI_h*.json"):
        try:
            os.link(p, dest / p.name)
        except OSError:  # khác filesystem: chép
            shutil.copy2(p, dest / p.name)
    return dest


def rewrite_metas(folder: Path, change) -> None:
    """Ghi lại mọi metadata thành file mới (không sửa qua hardlink) sau khi `change(meta)`."""
    for p in folder.glob("*.meta.json"):
        meta = json.loads(p.read_text())
        change(meta)
        p.unlink()
        p.write_text(json.dumps(meta))


@pytest.fixture
def model_dir(db, tmp_path, monkeypatch):
    """MODEL_DIR tạm, rỗng."""
    root = tmp_path / "xgb"
    root.mkdir()
    monkeypatch.setenv("MODEL_DIR", str(root))
    get_settings.cache_clear()
    yield root
    get_settings.cache_clear()


async def test_valid_bundle_is_registered_activated_and_loaded(model_dir):
    link_bundle(model_dir / "v1-no_fill")
    reg = Registry()
    report = await reg.rescan()
    [m] = report.models
    manifest = (SOURCE / "MANIFEST.sha256").read_text()
    assert (m.dir_name, m.status, m.is_active, m.nan_policy, m.required_history_hours) == (
        "v1-no_fill", "available", True, "no_fill", 73,
    )  # fmt: skip
    assert m.bundle_sha256 == hashlib.sha256(manifest.encode()).hexdigest()  # khớp MANIFEST.sha256
    assert m.horizons == list(HORIZONS) and m.feature_count == 184 and m.summary["3"]["n_trees"] > 0
    loaded = reg.current()
    assert loaded is not None and loaded.horizons == list(HORIZONS) and reg.loaded_sha() == m.bundle_sha256
    assert report.errors == {}


async def test_rescan_twice_is_idempotent(model_dir):
    link_bundle(model_dir / "v1-no_fill")
    reg = Registry()
    await reg.rescan()
    again = await reg.rescan()
    assert len(again.models) == 1 and again.models[0].is_active


@pytest.mark.parametrize(
    ("break_bundle", "reason"),
    [
        (lambda d: (d / "xgb_AQI_h72.json").unlink(), "Thiếu model horizon [72]"),
        (lambda d: (d / "xgb_AQI_h9.meta.json").unlink(), "Thiếu metadata horizon 9"),
        (lambda d: rewrite_metas(d, lambda m: m["feature_columns"].reverse()), "feature_columns"),
        (lambda d: rewrite_metas(d, lambda m: m["library_versions"].update(xgboost="2.1.4")), "phiên bản chính"),
        (lambda d: rewrite_metas(d, lambda m: m.update(nan_policy="no_fill")), "nan_policy"),
    ],
)
async def test_invalid_bundles_are_rejected(model_dir, break_bundle, reason):
    """Thiếu file, feature_columns lệch code, khác bản xgboost chính, nan_policy sai dạng → không kích hoạt."""
    break_bundle(link_bundle(model_dir / "broken"))
    reg = Registry()
    report = await reg.rescan()
    assert report.models == [] and reason in report.errors["broken"]
    assert reg.current() is None


async def test_minor_library_difference_only_warns(model_dir, caplog):
    rewrite_metas(link_bundle(model_dir / "v1"), lambda m: m["library_versions"].update(xgboost="3.3.0"))
    report = await Registry().rescan()
    assert report.models[0].status == "available"
    assert "xgboost lúc train 3.3.0, đang cài 3.4.1" in caplog.text


async def test_deleted_directory_becomes_missing_and_is_unloaded(model_dir):
    bundle = link_bundle(model_dir / "v1-no_fill")
    reg = Registry()
    await reg.rescan()
    shutil.rmtree(bundle)
    [m] = (await reg.rescan()).models
    assert (m.status, m.is_active) == ("missing", False)
    assert reg.current() is None


async def test_modified_file_makes_model_invalid(model_dir):
    """Thư mục đã dùng bị sửa (SHA khác) → invalid, bỏ kích hoạt: không dự báo bằng bộ không còn tái hiện được."""
    bundle = link_bundle(model_dir / "v1-no_fill")
    reg = Registry()
    await reg.rescan()
    rewrite_metas(bundle, lambda m: m.update(note="đã sửa"))
    [m] = (await reg.rescan()).models
    assert (m.status, m.is_active) == ("invalid", False) and "thay đổi" in m.status_reason
    assert reg.current() is None


async def test_two_bundles_need_explicit_activation_and_only_one_active(model_dir, db):
    link_bundle(model_dir / "v1")
    rewrite_metas(link_bundle(model_dir / "v2"), lambda m: m.update(note="bản 2"))
    reg = Registry()
    report = await reg.rescan()
    by_dir = {m.dir_name: m for m in report.models}
    assert not any(m.is_active for m in report.models) and reg.current() is None  # hai bản: không tự chọn

    await reg.activate(by_dir["v2"].id)
    assert reg.current().dir_name == "v2"
    await reg.activate(by_dir["v1"].id)
    assert reg.current().dir_name == "v1"
    assert rows(db, "SELECT dir_name FROM ml_models WHERE is_active") == [("v1",)]


async def test_activate_unavailable_model_fails(model_dir):
    bundle = link_bundle(model_dir / "v1-no_fill")
    reg = Registry()
    [m] = (await reg.rescan()).models
    shutil.rmtree(bundle)
    await reg.rescan()
    with pytest.raises(BundleInvalid):
        await reg.activate(m.id)


async def test_adapter_matches_src_predict(model_dir):
    """Adapter dùng model trong bộ nhớ cho đúng con số như `src.predict.predict` đọc file (24 mốc, so chính xác)."""
    link_bundle(model_dir / "v1-no_fill")
    reg = Registry()
    await reg.rescan()
    history = load_raw_dataset()
    t = pd.Timestamp("2026-09-22 23:00")
    preds, _ = adapter.predict(reg.current(), history, t, t)
    expected = ml_predict(history, t=t, now=t, models_dir=SOURCE)
    assert preds == dict(zip(expected["horizon_hours"], expected["predicted_aqi"], strict=True))
    with pytest.raises(adapter.InferenceDataError):  # dữ liệu cũ hơn 2 giờ so với now → từ chối (R16)
        adapter.predict(reg.current(), history, t, t + pd.Timedelta(hours=3))
