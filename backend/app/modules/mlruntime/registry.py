"""Registry model theo thư mục phiên bản (backend_design 8.1, 8.3).

- `inspect_bundle(path)`: kiểm tra một thư mục (thuần Python, chạy trong thread vì phải nạp 24 model).
- `rescan()`: quét MODEL_DIR, ghi `ml_models` (`available` / `invalid` / `missing`), tự kích hoạt khi chưa có bản
  active và chỉ có một bản hợp lệ, rồi nạp bản active vào bộ nhớ.
- `activate(model_id)`: kích hoạt một bản, NOTIFY `model_changed`; mọi tiến trình nạp lại theo `bundle_sha256`.
- Nạp xong cả bộ mới rồi mới thay con trỏ (`current()`), nên không có lúc trống. Không bao giờ nạp pickle/joblib.
"""

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path

import anyio
from sqlalchemy.ext.asyncio import AsyncSession
from src.feature_engineering import get_feature_columns
from src.train import load_model_and_metadata

from app.core import events, timeutil
from app.core.config import get_settings
from app.core.db import run_in_transaction
from app.modules.mlruntime import repository
from app.modules.mlruntime.models import MlModel

log = logging.getLogger(__name__)

HORIZONS = tuple(range(3, 73, 3))  # đủ 24 mốc 3–72 giờ (P6)
NAN_POLICIES = ("no_fill", "ffill3h", "xgb_native_nan")
_MODEL_FILE = re.compile(r"xgb_AQI_h(\d+)\.json")
_SAME_KEYS = ("model_version", "nan_policy", "feature_columns", "required_history_hours", "include_extra_features",
              "future_time_features")  # fmt: skip


class BundleInvalid(Exception):
    """Thư mục model không dùng được; `reason` ghi vào `ml_models.status_reason` và hiện ở Admin."""


@dataclass(frozen=True)
class BundleInfo:
    """Thông tin kiểm tra xong của một thư mục phiên bản (đủ để ghi `ml_models`)."""

    dir_name: str
    bundle_sha256: str
    model_version: str
    nan_policy: str
    required_history_hours: int
    feature_columns: list[str]
    feature_columns_sha256: str
    dataset_sha256: str | None
    library_versions: dict
    summary: dict
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LoadedBundle:
    """Bộ model đang dùng trong bộ nhớ: mỗi horizon một model XGBoost và metadata của nó."""

    model_id: int
    dir_name: str
    bundle_sha256: str
    models: dict[int, object]
    metas: dict[int, dict]

    @property
    def horizons(self) -> list[int]:
        return sorted(self.models)


def bundle_sha256(path: Path) -> str:
    """SHA-256 của danh sách "<sha256 file>  <tên file>" (đúng nội dung MANIFEST.sha256 do script tạo)."""
    lines = []
    for p in sorted(path.glob("xgb_AQI_h*.json")):
        lines.append(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n")
    return hashlib.sha256("".join(lines).encode()).hexdigest()


def inspect_bundle(path: Path) -> tuple[BundleInfo, dict[int, object], dict[int, dict]]:
    """Nạp và kiểm tra một thư mục phiên bản (§8.3). Sai điểm nào → BundleInvalid, không kích hoạt.

    Trả (thông tin, model theo horizon, metadata theo horizon).
    """
    found = sorted(int(m.group(1)) for p in path.glob("*.json") if (m := _MODEL_FILE.fullmatch(p.name)))
    if tuple(found) != HORIZONS:
        missing = sorted(set(HORIZONS) - set(found))
        raise BundleInvalid(
            f"Thiếu model horizon {missing}" if missing else f"Horizon lạ {sorted(set(found) - set(HORIZONS))}"
        )
    models, metas = {}, {}
    for h in HORIZONS:
        if not (path / f"xgb_AQI_h{h}.meta.json").is_file():
            raise BundleInvalid(f"Thiếu metadata horizon {h}")
        try:
            models[h], metas[h] = load_model_and_metadata(h, path)
        except Exception as exc:  # noqa: BLE001 — file hỏng: không dùng được
            raise BundleInvalid(f"Không nạp được model horizon {h}: {type(exc).__name__}") from None
        if metas[h].get("horizon_hours") != h:
            raise BundleInvalid(f"Metadata horizon {h} ghi horizon_hours={metas[h].get('horizon_hours')}")
    first = metas[HORIZONS[0]]
    for key in _SAME_KEYS:
        if any(m.get(key) != first.get(key) for m in metas.values()):
            raise BundleInvalid(f"Các file không cùng {key}")
    policy = first.get("nan_policy")
    if not isinstance(policy, dict) or policy.get("name") not in NAN_POLICIES:
        raise BundleInvalid(f"nan_policy không hợp lệ: {policy!r}")
    columns = get_feature_columns(
        policy["name"],
        include_future_time=bool(first.get("future_time_features")),
        include_extra=bool(first.get("include_extra_features")),
    )
    if first.get("feature_columns") != columns:
        raise BundleInvalid("feature_columns trong metadata khác get_feature_columns của code ML")
    warnings = _check_library_versions(first.get("library_versions") or {})
    if any(m.get("n_trees") is None for m in metas.values()):
        raise BundleInvalid("Metadata thiếu n_trees")
    info = BundleInfo(
        dir_name=path.name,
        bundle_sha256=bundle_sha256(path),
        model_version=first["model_version"],
        nan_policy=policy["name"],
        required_history_hours=first["required_history_hours"],
        feature_columns=columns,
        feature_columns_sha256=hashlib.sha256(json.dumps(columns).encode()).hexdigest(),
        dataset_sha256=first.get("dataset_sha256"),
        library_versions=first.get("library_versions") or {},
        summary={str(h): _summary(m) for h, m in metas.items()},
        warnings=warnings,
    )
    return info, models, metas


@dataclass(frozen=True)
class ScanReport:
    """Kết quả quét: mọi dòng `ml_models` và lỗi của thư mục chưa đăng ký được."""

    models: list[MlModel]
    errors: dict[str, str]


class Registry:
    """Trạng thái model trong tiến trình: bản active đang nạp. Trạng thái thật (bản nào active) nằm trong DB."""

    def __init__(self) -> None:
        self._loaded: LoadedBundle | None = None
        self._lock = anyio.Lock()
        self._tasks: set[asyncio.Task] = set()

    def current(self) -> LoadedBundle | None:
        """Bộ model đang dùng; None khi chưa có model hợp lệ (dự báo báo không sẵn sàng, API vẫn chạy)."""
        return self._loaded

    def loaded_sha(self) -> str | None:
        """SHA của bộ đang nạp ở tiến trình này (cho trang Hệ thống, MODEL_SYNCING)."""
        return self._loaded.bundle_sha256 if self._loaded else None

    async def rescan(self) -> ScanReport:
        """Quét MODEL_DIR, cập nhật `ml_models`, tự kích hoạt nếu được, rồi nạp bản active.

        Thư mục chưa từng hợp lệ không có dòng `ml_models` (thiếu thông tin bắt buộc) nên lỗi trả riêng ở `errors`.
        """
        root = Path(get_settings().model_dir)
        dirs = sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
        if not root.is_dir():
            log.warning("Không có thư mục model %s: dự báo tắt cho tới khi có bundle", root)
        results: dict[str, tuple[BundleInfo | None, str | None]] = {}
        for d in dirs:
            try:
                info, _, _ = await anyio.to_thread.run_sync(inspect_bundle, d)
                for w in info.warnings:
                    log.warning("Model %s: %s", d.name, w)
                results[d.name] = (info, None)
            except BundleInvalid as exc:
                log.warning("Model %s không hợp lệ: %s", d.name, exc)
                results[d.name] = (None, str(exc))
        models = await run_in_transaction(lambda s: _sync_db(s, results))
        await self.sync_active()
        known = {m.dir_name for m in models}
        errors = {name: reason for name, (info, reason) in results.items() if info is None and name not in known}
        return ScanReport(models=models, errors=errors)

    async def activate(self, model_id: int, user_id: int | None = None) -> MlModel:
        """Kích hoạt một phiên bản `available`; NOTIFY `model_changed` cùng transaction rồi nạp lại."""

        async def work(session: AsyncSession) -> MlModel:
            model = await repository.get(session, model_id, for_update=True)
            if model is None or model.status != "available":
                raise BundleInvalid("Chỉ kích hoạt được phiên bản có trạng thái available")
            await repository.deactivate_all(session)
            await session.flush()
            await repository.set_active(session, model_id, timeutil.now(), user_id)
            await events.notify(session, "model_changed", {"model_id": model_id, "bundle_sha256": model.bundle_sha256})
            return model

        model = await run_in_transaction(work)
        await self.sync_active()
        return model

    async def sync_active(self) -> LoadedBundle | None:
        """Nạp đúng bản active trong DB (theo SHA); không còn bản active thì bỏ bộ đang dùng."""
        async with self._lock:
            active = await run_in_transaction(repository.active)
            if active is None:
                self._loaded = None
                return None
            if self._loaded and self._loaded.bundle_sha256 == active.bundle_sha256:
                return self._loaded
            path = Path(get_settings().model_dir) / active.dir_name
            try:
                info, models, metas = await anyio.to_thread.run_sync(inspect_bundle, path)
            except BundleInvalid as exc:
                log.error("Không nạp được model active %s: %s", active.dir_name, exc)
                self._loaded = None
                return None
            if info.bundle_sha256 != active.bundle_sha256:
                log.error("Model active %s đã bị sửa (SHA khác DB): không dùng", active.dir_name)
                self._loaded = None
                return None
            # Nạp xong cả bộ rồi mới thay con trỏ
            self._loaded = LoadedBundle(active.id, active.dir_name, active.bundle_sha256, models, metas)
            log.info("Đã nạp model %s (%s)", active.dir_name, active.bundle_sha256[:12])
            return self._loaded

    def on_event(self, event: dict) -> None:
        """Người nghe EventHub (chạy trong event loop): đổi model ở tiến trình nào cũng nạp lại theo DB."""
        if event.get("type") == "model_changed":
            task = asyncio.get_running_loop().create_task(self.sync_active())
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)


registry = Registry()


async def _sync_db(session: AsyncSession, results: dict[str, tuple[BundleInfo | None, str | None]]) -> list[MlModel]:
    """Ghi kết quả quét vào `ml_models`; bản active hỏng/mất thì bỏ kích hoạt; tự kích hoạt nếu chỉ có một bản."""
    now = timeutil.now()
    known = {m.dir_name: m for m in await repository.all_models(session)}
    for name, (info, reason) in results.items():
        model = known.get(name)
        if info is None:
            if model is not None:
                model.status, model.status_reason = "invalid", reason
            continue
        if model is None:
            model = MlModel(dir_name=name, first_loaded_at=now)
            session.add(model)
            known[name] = model
            _fill(model, info)
        elif model.bundle_sha256 != info.bundle_sha256:
            # Thư mục đã dùng bị sửa: không tái hiện được dự báo cũ (R8)
            model.status, model.status_reason = "invalid", "File model đã thay đổi so với lúc đăng ký"
            continue
        model.status, model.status_reason, model.last_loaded_at = "available", None, now
    for name, model in known.items():
        if name not in results:
            model.status, model.status_reason = "missing", "Thư mục model không còn"
    for model in known.values():
        if model.is_active and model.status != "available":
            model.is_active = False
    await session.flush()
    available = [m for m in known.values() if m.status == "available"]
    if not any(m.is_active for m in known.values()) and len(available) == 1:
        await repository.set_active(session, available[0].id, now, None)
        await events.notify(
            session, "model_changed", {"model_id": available[0].id, "bundle_sha256": available[0].bundle_sha256}
        )
    return await repository.all_models(session)


def _fill(model: MlModel, info: BundleInfo) -> None:
    """Chép thông tin bundle vào dòng ml_models mới."""
    model.model_version = info.model_version
    model.bundle_sha256 = info.bundle_sha256
    model.algorithm = "xgboost"
    model.horizons = list(HORIZONS)
    model.nan_policy = info.nan_policy
    model.required_history_hours = info.required_history_hours
    model.feature_count = len(info.feature_columns)
    model.feature_columns_sha256 = info.feature_columns_sha256
    model.dataset_sha256 = info.dataset_sha256
    model.library_versions = info.library_versions
    model.summary = info.summary
    model.is_active = False


def _summary(meta: dict) -> dict:
    """Tóm tắt theo horizon cho Admin: số cây, MAE/RMSE của XGBoost trên val/test lúc train."""
    out = {"n_trees": meta.get("n_trees")}
    for m in meta.get("metrics") or []:
        if m.get("method") == "xgboost":
            out[f"{m['segment']}_mae"] = m.get("MAE")
            out[f"{m['segment']}_rmse"] = m.get("RMSE")
    return out


def _check_library_versions(versions: dict) -> list[str]:
    """xgboost/pandas lúc train so với bản đang cài: lệch bản chính → BundleInvalid; lệch bản phụ → cảnh báo."""
    warnings = []
    for lib in ("xgboost", "pandas"):
        trained = versions.get(lib)
        try:
            installed = metadata.version(lib)
        except metadata.PackageNotFoundError:
            raise BundleInvalid(f"Chưa cài {lib}") from None
        if not trained:
            warnings.append(f"Metadata không ghi phiên bản {lib}")
            continue
        if trained.split(".")[0] != installed.split(".")[0]:
            raise BundleInvalid(f"{lib} lúc train {trained}, đang cài {installed} (khác phiên bản chính)")
        if trained != installed:
            warnings.append(f"{lib} lúc train {trained}, đang cài {installed}")
    return warnings
