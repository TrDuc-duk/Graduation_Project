#!/usr/bin/env python3
"""Gửi dữ liệu cảm biến giả lập vào dashboard, chỉ cần Python 3.10+.

Chạy từ thư mục gốc dự án:
  python3 backend/scripts/demo_sensors.py
  python3 backend/scripts/demo_sensors.py --scenario polluted --minutes 10
  python3 backend/scripts/demo_sensors.py --base https://your-host --once
  python3 backend/scripts/demo_sensors.py --dry-run

Mặc định: 3 node, gửi mỗi 5 giây, chạy đến Ctrl+C. Tự đăng ký thiết bị
DEMO rồi lưu ID để tái sử dụng. --state FILE tách một bộ thiết bị khác.
Cấu hình: biến môi trường ưu tiên hơn --env-file (mặc định docker/.env,
nếu không có thì backend/.env). Các khóa: GATEWAY_SECRETS, PROVISION_KEY,
API_PORT. Không lưu secret vào file trạng thái hoặc in payload xác thực.

Dashboard cần ENABLE_DEV_ENDPOINTS=true (docker-compose.dev.yml đã bật).
Thiết bị mới ở trạng thái pending: dashboard dev vẫn hiển thị số đo thô;
dữ liệu cách ly chưa được dùng cho tổng hợp/ML. Chạy trước vài phút để
biểu đồ có dữ liệu; script không chèn lịch sử hoặc giả thời gian đo.
"""

import argparse
import json
import math
import os
import random
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT = BACKEND_DIR.parent
GATEWAY_PATTERN = r"[A-Za-z0-9_-]{1,15}"
NODE_PATTERN = r"NODE_\d{3}"


class ApiError(Exception):
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def read_env(path):
    """Đọc KEY=value đơn giản, không thực thi shell hoặc nội suy biến."""
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        value = value.strip()
        if value.startswith(("'", '"')) and value[-1:] == value[:1]:
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        values[key.strip()] = value
    return values


def post(base, path, body):
    request = Request(
        base + path,
        data=json.dumps(body, allow_nan=False).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:
            result = json.load(response)
    except HTTPError as exc:
        hints = {
            401: "Kiểm tra GATEWAY_SECRETS / PROVISION_KEY.",
            403: "Kiểm tra PROVISION_KEY.",
            404: "Kiểm tra --base và đường dẫn /api/v1.",
            429: "Đã chạm giới hạn request; đợi ít nhất 60 giây.",
        }
        raise ApiError(
            f"{path}: HTTP {exc.code}. {hints.get(exc.code, 'Backend từ chối request.')}",
            retryable=exc.code == 429 or exc.code >= 500,
        ) from None
    except (URLError, TimeoutError, OSError):
        raise ApiError(f"{path}: không kết nối được backend; kiểm tra địa chỉ và dịch vụ.", True) from None
    except ValueError:
        raise ApiError(f"{path}: phản hồi không phải JSON; kiểm tra --base.") from None
    if not isinstance(result, dict) or result.get("success") is not True:
        raise ApiError(f"{path}: backend không xác nhận success=true.")
    return result


def save_state(path, state):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def setup(args, provision_key):
    if args.gateway_id:
        return {"gateway_id": args.gateway_id, "nodes": args.node_ids}
    state = {"base": args.base, "nodes": []}
    if args.state.exists():
        state = json.loads(args.state.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or state.get("base") != args.base:
            raise ValueError("File trạng thái thuộc backend khác; chọn --state khác.")
        gateway = state.get("gateway_id", "")
        nodes = state.get("nodes")
        if (
            not isinstance(gateway, str)
            or not re.fullmatch(GATEWAY_PATTERN, gateway)
            or not isinstance(nodes, list)
            or not all(valid_node(node) for node in nodes)
            or len(set(nodes)) != len(nodes)
        ):
            raise ValueError("File trạng thái không hợp lệ; kiểm tra hoặc chọn --state khác.")
        if len(nodes) > args.nodes:
            raise ValueError(f"Bộ demo đã có {len(nodes)} node; dùng --nodes {len(nodes)} hoặc --state khác.")
    else:
        result = post(
            args.base,
            "/provision/gateway",
            {
                "provision_key": provision_key,
                "name": "DEMO - Gateway giả lập",
                "location_desc": "Dữ liệu giả lập phục vụ trình diễn",
            },
        )
        state["gateway_id"] = result["data"]["id"]
        save_state(args.state, state)
    while len(state["nodes"]) < args.nodes:
        index = len(state["nodes"])
        result = post(
            args.base,
            "/provision/node",
            {
                "provision_key": provision_key,
                "gateway_id": state["gateway_id"],
                "name": f"DEMO - Trạm giả lập {index + 1}",
                "lat": round(21.0045 + index * 0.008, 6),
                "lng": round(105.8431 + index * 0.006, 6),
            },
        )
        state["nodes"].append(result["data"]["id"])
        # Lưu sau từng lần đăng ký để chạy lại tiếp được khi mạng gián đoạn.
        save_state(args.state, state)
    return state


def valid_node(value):
    return isinstance(value, str) and re.fullmatch(NODE_PATTERN, value) is not None and 1 <= int(value[5:]) <= 255


def reading(node, index, elapsed, scenario):
    if scenario == "mixed":
        scenario = "polluted" if index == 0 else "clean"
    phase = elapsed * 2 * math.pi / 180 + index * 0.65
    level = {"clean": 6, "moderate": 25, "polluted": 85}.get(scenario)
    if level is None:
        level = 6 + 79 * (1 - math.cos(phase)) / 2
    pm25 = round(max(1, level + 1.5 * math.sin(phase * 2) + random.uniform(-0.7, 0.7)), 1)
    return {
        "node_id": node,
        "pm25": pm25,
        "pm10": round(pm25 * 1.45 + random.uniform(3, 6), 1),
        "co2": round(450 + pm25 * 7 + random.uniform(-15, 15)),
        "tvoc": round(15 + pm25 * 2.5 + random.uniform(-5, 5)),
        "temperature": round(28 + index * 0.3 + math.sin(phase) + random.uniform(-0.1, 0.1), 1),
        "humidity": round(65 + 5 * math.cos(phase) + random.uniform(-0.4, 0.4), 1),
        "battery": max(60, 98 - index * 4 - int(elapsed / 600)),
        "rssi": 0,
        # Như gateway-30pin: không gửi msg_id, server dùng thời điểm nhận.
    }


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", help="URL backend hoặc web có proxy /api; mặc định localhost:API_PORT hoặc 8001")
    parser.add_argument("--env-file", type=Path, help="File .env chứa khóa backend")
    parser.add_argument("--state", type=Path, default=BACKEND_DIR / ".demo-sensors.json", help="File lưu ID thiết bị")
    parser.add_argument("--nodes", type=int, default=3, help="Số node đăng ký: 1–8 (mặc định 3)")
    parser.add_argument("--gateway-id", help="Gateway có sẵn; phải truyền kèm --node-ids")
    parser.add_argument("--node-ids", nargs="+", help="Node có sẵn, ví dụ NODE_001 NODE_002")
    parser.add_argument("--interval", type=float, default=5, help="Giây giữa hai đợt gửi, tối thiểu 2")
    parser.add_argument("--minutes", type=float, default=0, help="Thời gian chạy; 0 = đến khi Ctrl+C")
    parser.add_argument(
        "--scenario",
        choices=["cycle", "clean", "moderate", "polluted", "mixed"],
        default="cycle",
        help="mixed: trạm đầu ô nhiễm, các trạm còn lại tốt",
    )
    parser.add_argument("--once", action="store_true", help="Gửi một đợt rồi thoát")
    parser.add_argument("--dry-run", action="store_true", help="In số đo mẫu, không kết nối hoặc tạo thiết bị")
    args = parser.parse_args()
    if not 1 <= args.nodes <= 8:
        parser.error("--nodes phải từ 1 đến 8 để phù hợp giới hạn provisioning.")
    if not math.isfinite(args.interval) or args.interval < 2:
        parser.error("--interval phải là số hữu hạn >= 2.")
    if not math.isfinite(args.minutes) or args.minutes < 0:
        parser.error("--minutes phải là số hữu hạn >= 0.")
    if bool(args.gateway_id) != bool(args.node_ids):
        parser.error("--gateway-id và --node-ids phải đi cùng nhau.")
    if args.gateway_id and not re.fullmatch(GATEWAY_PATTERN, args.gateway_id):
        parser.error("Gateway ID phải có 1–15 ký tự chữ, số, _ hoặc -.")
    if args.node_ids and (
        len(args.node_ids) > 8
        or len(set(args.node_ids)) != len(args.node_ids)
        or not all(valid_node(node) for node in args.node_ids)
    ):
        parser.error("--node-ids cần 1–8 mã khác nhau trong NODE_001 đến NODE_255.")
    return args


def main():
    args = parse_args()
    if args.dry_run:
        nodes = args.node_ids or [f"NODE_{i + 1:03d}" for i in range(args.nodes)]
        print(json.dumps([reading(node, i, 0, args.scenario) for i, node in enumerate(nodes)], indent=2))
        return
    env_file = args.env_file or next(
        (path for path in [ROOT / "docker/.env", BACKEND_DIR / ".env"] if path.exists()), None
    )
    config = read_env(env_file) if env_file else {}
    config.update(os.environ)
    base = (args.base or f"http://localhost:{config.get('API_PORT') or '8001'}").rstrip("/")
    url = urlsplit(base)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise ValueError("--base phải là URL http(s), không chứa tài khoản, query hoặc fragment.")
    args.base = base if base.endswith("/api/v1") else base + "/api/v1"
    secret = (config.get("GATEWAY_SECRETS") or "").split(",")[0].strip()
    provision_key = config.get("PROVISION_KEY") or ""
    if not secret or not provision_key:
        raise SystemExit("Thiếu GATEWAY_SECRETS hoặc PROVISION_KEY: đặt trong docker/.env hoặc --env-file.")
    state = setup(args, provision_key)
    print(f"DEMO → {args.base} | {state['gateway_id']} | {', '.join(state['nodes'])}", flush=True)
    print("Mở web, chọn trạm DEMO; web cập nhật mỗi 10 giây. Ctrl+C để dừng.", flush=True)
    print("Node/Gateway mới chờ duyệt; dashboard dev vẫn xem được số đo thô.", flush=True)
    auth = {"gateway_id": state["gateway_id"], "secret": secret}
    start = time.monotonic()
    last_heartbeat = -math.inf
    while True:
        now = time.monotonic()
        if args.minutes and now - start >= args.minutes * 60:
            break
        try:
            if now - last_heartbeat >= 300:
                post(args.base, "/telemetry/heartbeat", auth)
                last_heartbeat = now
            data = [reading(node, i, now - start, args.scenario) for i, node in enumerate(state["nodes"])]
            result = post(args.base, "/telemetry", {**auth, "data": data})
            accepted = result.get("accepted")
            if not isinstance(accepted, int) or accepted <= 0 or result.get("rejected", 0):
                raise ApiError("Backend không nhận đủ số đo mới; kiểm tra trạng thái Gateway/node và file --state.")
            values = " | ".join(f"{item['node_id']}: PM2.5={item['pm25']}" for item in data)
            print(f"[{time.strftime('%H:%M:%S')}] nhận {accepted}/{len(data)} · {values}", flush=True)
            if args.once:
                return
            delay = args.interval
        except ApiError as exc:
            if args.once or not exc.retryable:
                raise
            print(f"{exc} Thử gửi số đo mới sau 60 giây.", file=sys.stderr, flush=True)
            delay = 60
        if args.minutes:
            delay = min(delay, max(0, args.minutes * 60 - (time.monotonic() - start)))
        time.sleep(delay)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nĐã dừng demo. Lần chạy sau sẽ dùng lại thiết bị đã lưu.")
    except (ApiError, ValueError, OSError, KeyError, TypeError) as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        sys.exit(1)
