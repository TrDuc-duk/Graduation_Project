"""Cổng thiết bị: 5 endpoint firmware gọi (backend_design 6.1, 6.2, 6.8, 14.2).

Firmware chỉ coi 200 là gửi telemetry thành công; provisioning chờ 201 và đọc `data.id` (node đọc thêm
`data.node_numeric_id`). Lỗi trả dạng {"success": false, "error": "..."}; câu chữ giữ như datn-main.
"""

import json
import logging
from typing import NoReturn

from fastapi import APIRouter, Request
from pydantic import BaseModel, ValidationError

from app.core import ratelimit, security_events, settings_store, timeutil
from app.core.config import get_settings
from app.core.db import run_in_transaction
from app.core.errors import DeviceError
from app.core.ratelimit import client_ip
from app.core.security import matches_any
from app.modules.devices import service as devices
from app.modules.ingest import pipeline
from app.modules.ingest.schemas import (
    MAX_ITEMS,
    HeartbeatIn,
    ProvisionGatewayIn,
    ProvisionNodeIn,
    TelemetryIn,
)
from app.modules.telemetry import service as telemetry

log = logging.getLogger(__name__)

router = APIRouter(tags=["device"])

MAX_BODY_BYTES = 32 * 1024
PROVISION_LIMIT_PER_MIN = 10


# ---------- hàm dùng chung ----------


async def read_json(request: Request) -> dict:
    """Đọc body JSON dạng object; quá 32 KB → 413, không phải JSON object → 400."""
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise DeviceError(413, "Payload quá lớn")
    try:
        data = json.loads(body)
    except ValueError:
        raise DeviceError(400, "Body không phải JSON hợp lệ") from None
    if not isinstance(data, dict):
        raise DeviceError(400, "Body phải là JSON object")
    return data


def parse[M: BaseModel](model: type[M], data: dict) -> M:
    """Kiểm tra body theo schema; sai thì 400 kèm trường lỗi đầu tiên."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        field = ".".join(str(p) for p in first["loc"]) or "body"
        raise DeviceError(400, f"Dữ liệu không hợp lệ: {field}") from None


async def reject(
    status: int, message: str, *, kind: str, ip: str | None, gateway_id: str | None = None, raw: dict | None = None
) -> NoReturn:
    """Ghi request bị từ chối vào ingest_batches (transaction riêng) rồi trả lỗi theo dạng firmware."""
    try:
        await telemetry.log_batch_now(
            received_at=timeutil.now(),
            kind=kind,
            gateway_id=gateway_id,
            remote_ip=ip,
            http_status=status,
            error=message,
            payload=telemetry.strip_secrets(raw),
        )
    except Exception:  # noqa: BLE001 — DB lỗi vẫn phải trả mã lỗi cho thiết bị
        log.exception("Không ghi được ingest_batches cho request bị từ chối")
    raise DeviceError(status, message)


async def check_device_secret(raw: dict, ip: str | None, kind: str) -> None:
    """Sai/thiếu secret → 401 và sự kiện bảo mật; IP gửi lỗi quá 20 lần/phút → 429."""
    if matches_any(raw.get("secret"), get_settings().gateway_secrets):
        return
    gateway_id = raw.get("gateway_id") if isinstance(raw.get("gateway_id"), str) else None
    await security_events.record_now("device_auth_failed", "warning", source_ip=ip, gateway_id=gateway_id)
    if not await ip_error_allowed(ip):
        await reject(429, "Quá nhiều request lỗi", kind=kind, ip=ip, gateway_id=gateway_id)
    await reject(401, "Sai Secret Key. Máy chủ từ chối tiếp nhận gói tin.", kind=kind, ip=ip, gateway_id=gateway_id)


async def ip_error_allowed(ip: str | None) -> bool:
    """Đếm một request lỗi (hoặc Gateway lạ) của IP; False khi vượt telemetry_ip_error_limit_per_min."""
    limit = await settings_store.get("telemetry_ip_error_limit_per_min")
    if await ratelimit.hit(f"telemetry:ip:{ip}", limit):
        return True
    await security_events.record_now("rate_limited", "warning", source_ip=ip, scope="telemetry_ip")
    return False


async def check_telemetry_rate(gateway_id: str, ip: str | None, kind: str) -> None:
    """Giới hạn sau khi secret đúng: toàn hệ thống (503), theo Gateway đã biết (429), Gateway lạ tính theo IP."""
    limits = await settings_store.get_many("telemetry_global_limit_per_min", "telemetry_gateway_limit_per_min")
    if not await ratelimit.hit("telemetry:global", limits["telemetry_global_limit_per_min"]):
        await security_events.record_now("rate_limited", "warning", source_ip=ip, gateway_id=gateway_id, scope="global")
        await reject_after_auth(503, "Máy chủ đang quá tải", kind=kind, ip=ip, gateway_id=gateway_id)
    known = await run_in_transaction(lambda s: devices.gateway_exists(s, gateway_id))
    if known:
        if await ratelimit.hit(f"telemetry:gw:{gateway_id}", limits["telemetry_gateway_limit_per_min"]):
            return
        await security_events.record_now("rate_limited", "warning", source_ip=ip, gateway_id=gateway_id, scope="gw")
        await reject_after_auth(429, "Quá nhiều request", kind=kind, ip=ip, gateway_id=gateway_id)
    if not await ip_error_allowed(ip):
        await reject(429, "Quá nhiều request", kind=kind, ip=ip, gateway_id=gateway_id)


async def reject_after_auth(status: int, message: str, *, kind: str, ip: str | None, gateway_id: str) -> NoReturn:
    """Từ chối request đã đúng secret: đánh dấu Gateway bị từ chối để batch kế tiếp bị coi là nghi cũ (6.2)."""
    if kind == "telemetry":
        try:
            await run_in_transaction(lambda s: devices.mark_telemetry_rejected(s, gateway_id, timeutil.now()))
        except Exception:  # noqa: BLE001
            log.exception("Không ghi được telemetry_rejected_since cho %s", gateway_id)
    await reject(status, message, kind=kind, ip=ip, gateway_id=gateway_id)


# ---------- telemetry ----------


@router.post("/telemetry")
async def post_telemetry(request: Request) -> dict:
    """Nhận batch số đo từ Gateway. Batch đúng cú pháp luôn được trả 200 (kể cả bản trùng, thiết bị lạ)."""
    ip = client_ip(request)
    raw = await read_json(request)
    await check_device_secret(raw, ip, "telemetry")
    if not isinstance(raw.get("gateway_id"), str) or not isinstance(raw.get("data"), list):
        if not await ip_error_allowed(ip):
            await reject(429, "Quá nhiều request lỗi", kind="telemetry", ip=ip)
        await reject(400, "Payload data rỗng hoặc sai định dạng. Yêu cầu là một Array.", kind="telemetry", ip=ip)
    body = parse(TelemetryIn, raw)
    await check_telemetry_rate(body.gateway_id, ip, "telemetry")
    if len(body.data) > MAX_ITEMS:
        await reject_after_auth(413, "Quá nhiều bản ghi", kind="telemetry", ip=ip, gateway_id=body.gateway_id)

    try:
        result = await pipeline.ingest_telemetry(body, raw, ip)
    except Exception:  # noqa: BLE001 — lỗi DB/hết lượt thử: Gateway giữ batch và gửi lại (an toàn nhờ chống trùng)
        log.exception("Ingest batch của %s lỗi", body.gateway_id)
        await reject_after_auth(
            503, "Lỗi máy chủ, vui lòng gửi lại", kind="telemetry", ip=ip, gateway_id=body.gateway_id
        )
    return result.response()


@router.post("/telemetry/heartbeat")
async def post_heartbeat(request: Request) -> dict:
    """Heartbeat Gateway 5 phút/lần (firmware không thử lại)."""
    ip = client_ip(request)
    raw = await read_json(request)
    await check_device_secret(raw, ip, "heartbeat")
    body = parse(HeartbeatIn, raw)
    await check_telemetry_rate(body.gateway_id, ip, "heartbeat")
    try:
        await pipeline.ingest_heartbeat(body.gateway_id, ip)
    except Exception:  # noqa: BLE001
        log.exception("Heartbeat của %s lỗi", body.gateway_id)
        await reject(503, "Lỗi máy chủ", kind="heartbeat", ip=ip, gateway_id=body.gateway_id)
    return {"success": True, "message": "Heartbeat OK"}


# ---------- provisioning (6.8) ----------


async def check_provision(key: object, ip: str | None, raw: dict | None) -> None:
    """Giới hạn 10 request/phút/IP; thiếu provision_key → 401, sai → 403 (như datn-main)."""
    if not await ratelimit.hit(f"provision:ip:{ip}", PROVISION_LIMIT_PER_MIN):
        await security_events.record_now("rate_limited", "warning", source_ip=ip, scope="provision")
        await reject(429, "Quá nhiều request", kind="provision", ip=ip, raw=raw)
    if not key:
        await security_events.record_now("device_auth_failed", "warning", source_ip=ip, scope="provision")
        await reject(401, "Thiếu mã xác thực (provision_key)", kind="provision", ip=ip, raw=raw)
    if not isinstance(key, str) or not matches_any(key, [get_settings().provision_key]):
        await security_events.record_now("device_auth_failed", "warning", source_ip=ip, scope="provision")
        await reject(403, "Mã xác thực không hợp lệ", kind="provision", ip=ip, raw=raw)


@router.post("/provision/gateway", status_code=201)
async def provision_gateway(request: Request) -> dict:
    """Cổng cấu hình Gateway đăng ký: cấp mã GW_xxx, trạng thái pending chờ Admin duyệt."""
    ip = client_ip(request)
    raw = await read_json(request)
    await check_provision(raw.get("provision_key"), ip, raw)
    body = parse(ProvisionGatewayIn, raw)

    async def work(session) -> dict:
        gateway = await devices.provision_gateway(session, body.name, body.location_desc)
        await _log_provision(session, ip, gateway.id, raw)
        return {
            "id": gateway.id,
            "name": gateway.name,
            "location_desc": gateway.location_desc,
            "status": gateway.status,
        }

    return {"success": True, "data": await run_in_transaction(work)}


@router.get("/provision/gateways")
async def list_gateways(request: Request, provision_key: str | None = None) -> dict:
    """Danh sách Gateway active cho cổng cấu hình node chọn (chỉ id, name, location_desc, status)."""
    await check_provision(provision_key, client_ip(request), None)
    gateways = await run_in_transaction(devices.list_active_gateways)
    data = [{"id": g.id, "name": g.name, "status": g.status, "location_desc": g.location_desc} for g in gateways]
    return {"success": True, "data": data}


@router.post("/provision/node", status_code=201)
async def provision_node(request: Request) -> dict:
    """Cổng cấu hình node đăng ký: cấp địa chỉ LoRa (node_numeric_id) và mã trạm, trạng thái pending."""
    ip = client_ip(request)
    raw = await read_json(request)
    await check_provision(raw.get("provision_key"), ip, raw)
    body = parse(ProvisionNodeIn, raw)

    async def work(session) -> dict:
        node = await devices.provision_node(session, body.name, body.gateway_id, body.lat, body.lng, timeutil.now())
        await _log_provision(session, ip, body.gateway_id, raw)
        return {
            "id": node.device_code,
            "node_numeric_id": node.lora_addr,
            "station_code": node.station_code,
            "name": node.name,
            "gateway_id": node.home_gateway_id,
            "status": node.status,
            "lat": body.lat,
            "lng": body.lng,
        }

    try:
        data = await run_in_transaction(work)
    except devices.UnknownGatewayError:
        await reject(400, "Gateway không tồn tại!", kind="provision", ip=ip, gateway_id=body.gateway_id, raw=raw)
    except devices.NoFreeAddressError:
        await reject(409, "Mạng LoRa đã hết địa chỉ node", kind="provision", ip=ip, gateway_id=body.gateway_id, raw=raw)
    return {"success": True, "data": data}


async def _log_provision(session, ip: str | None, gateway_id: str | None, raw: dict) -> None:
    """Ghi lần provisioning thành công vào ingest_batches. TODO(M4): ghi thêm audit_logs qua module audit."""
    await telemetry.log_batch(
        session,
        received_at=timeutil.now(),
        kind="provision",
        gateway_id=gateway_id,
        remote_ip=ip,
        http_status=201,
        payload=telemetry.strip_secrets(raw),
    )
