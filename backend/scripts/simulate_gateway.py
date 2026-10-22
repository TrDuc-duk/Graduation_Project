"""Mô phỏng Gateway + node gửi dữ liệu đúng như firmware datn-main (chạy theo thời gian thật).

Hành vi firmware được mô phỏng (backend_design 6.6.1):
- node gửi một gói mỗi `--interval` giây; msg_id là bộ đếm 1 byte (bản `gateway`), bản `gateway-30pin` không gửi;
- Gateway giữ tối đa 10 gói; buffer đầy thì bỏ gói MỚI; xả khi đầy hoặc 30 giây sau lần xả trước;
- gửi lỗi (khác 200) thì giữ nguyên buffer để gửi lại; mất mạng thì không xả;
- heartbeat Gateway mỗi 5 phút.

Ví dụ:
    python scripts/simulate_gateway.py --base http://localhost:8001 --nodes 3 --interval 15 --minutes 5
    python scripts/simulate_gateway.py --variant gateway-30pin --offline-at 60 --offline-for 120
    python scripts/simulate_gateway.py --gateway-id GW_001 --resend-prob 0.2   # Gateway đã có, gửi lại batch
"""

import argparse
import asyncio
import random
import time

import httpx

SECRET = "super-secret-key"
PROVISION_KEY = "airquality2026"
BUFFER_SIZE = 10
FLUSH_INTERVAL_S = 30
HEARTBEAT_INTERVAL_S = 300


class SimGateway:
    """Một Gateway mô phỏng với các node của nó."""

    def __init__(self, args: argparse.Namespace, client: httpx.AsyncClient, gateway_id: str, node_ids: list[int]):
        self.args = args
        self.client = client
        self.gateway_id = gateway_id
        self.node_ids = node_ids
        self.msg_counter = {n: random.randint(0, 255) for n in node_ids}
        self.buffer: list[dict] = []
        self.stats = {"sent": 0, "ok": 0, "failed": 0, "dropped": 0, "resent": 0}

    def reading(self, node: int) -> dict:
        """Một gói số đo ngẫu nhiên quanh mức ô nhiễm Hà Nội, định dạng như http_client.cpp."""
        pm25 = round(random.gauss(45, 15), 1)
        packet = {
            "node_id": f"NODE_{node:03d}",
            "pm25": max(pm25, 1.0),
            "pm10": round(max(pm25, 1.0) * random.uniform(1.2, 1.8), 1),
            "co2": random.randint(450, 1200),
            "tvoc": random.randint(10, 300),
            "temperature": round(random.uniform(26, 34), 1),
            "humidity": round(random.uniform(55, 90), 1),
            "battery": random.randint(60, 100),
            "rssi": 0,
        }
        if self.args.variant == "gateway":
            packet["msg_id"] = self.msg_counter[node]
        self.msg_counter[node] = (self.msg_counter[node] + 1) % 256
        return packet

    def offline(self, elapsed: float) -> bool:
        """Đang trong khoảng mất mạng mô phỏng không."""
        start = self.args.offline_at
        return start is not None and start <= elapsed < start + self.args.offline_for

    async def post(self, path: str, body: dict) -> int:
        """Gửi một request; lỗi mạng tính như mã 0."""
        try:
            r = await self.client.post(f"{self.args.base}/api/v1{path}", json=body, timeout=10)
            return r.status_code
        except httpx.HTTPError:
            return 0

    async def flush(self) -> None:
        """Xả toàn bộ buffer trong một POST, thử 3 lần (nghỉ 1 rồi 2 giây); chỉ 200 mới làm rỗng buffer."""
        body = {"gateway_id": self.gateway_id, "secret": SECRET, "data": list(self.buffer)}
        for attempt in range(1, 4):
            self.stats["sent"] += 1
            status = await self.post("/telemetry", body)
            if status == 200:
                self.stats["ok"] += 1
                self.buffer.clear()
                if random.random() < self.args.resend_prob:  # phản hồi 200 không tới Gateway → gửi lại
                    self.stats["resent"] += 1
                    await self.post("/telemetry", body)
                return
            self.stats["failed"] += 1
            print(f"[{self.gateway_id}] telemetry lỗi {status}, thử lại lần {attempt}")
            if attempt < 3:
                await asyncio.sleep(attempt)

    async def run(self) -> None:
        """Vòng lặp mỗi giây: node gửi gói theo chu kỳ, Gateway xả buffer và gửi heartbeat theo lịch."""
        start = time.monotonic()
        next_send = {n: start + random.uniform(0, self.args.interval) for n in self.node_ids}
        last_flush = last_heartbeat = start - HEARTBEAT_INTERVAL_S
        while (now := time.monotonic()) - start < self.args.minutes * 60:
            for n in self.node_ids:
                if now >= next_send[n]:
                    next_send[n] += self.args.interval
                    packet = self.reading(n)
                    if len(self.buffer) < BUFFER_SIZE:
                        self.buffer.append(packet)
                    else:
                        self.stats["dropped"] += 1  # buffer đầy: firmware bỏ gói mới
            elapsed = now - start
            if not self.offline(elapsed):
                if now - last_heartbeat >= HEARTBEAT_INTERVAL_S:
                    last_heartbeat = now
                    status = await self.post("/telemetry/heartbeat", {"gateway_id": self.gateway_id, "secret": SECRET})
                    print(f"[{self.gateway_id}] heartbeat {status}")
                if self.buffer and (len(self.buffer) >= BUFFER_SIZE or now - last_flush >= FLUSH_INTERVAL_S):
                    last_flush = now
                    await self.flush()
            await asyncio.sleep(1)
        print(f"[{self.gateway_id}] xong: {self.stats}, còn {len(self.buffer)} gói trong buffer")


async def provision(args: argparse.Namespace, client: httpx.AsyncClient, index: int) -> tuple[str, list[int]]:
    """Đăng ký Gateway và các node như cổng cấu hình của firmware; trả (mã Gateway, địa chỉ node)."""
    if args.gateway_id:
        gateway_id = args.gateway_id
    else:
        r = await client.post(
            f"{args.base}/api/v1/provision/gateway",
            json={"provision_key": PROVISION_KEY, "name": f"Gateway mô phỏng {index + 1}", "location_desc": "sim"},
        )
        r.raise_for_status()
        gateway_id = r.json()["data"]["id"]
    nodes = []
    for i in range(args.nodes):
        r = await client.post(
            f"{args.base}/api/v1/provision/node",
            json={
                "provision_key": PROVISION_KEY,
                "name": f"Node mô phỏng {gateway_id}-{i + 1}",
                "gateway_id": gateway_id,
                "lat": round(21.0 + random.uniform(-0.05, 0.05), 5),
                "lng": round(105.85 + random.uniform(-0.05, 0.05), 5),
            },
        )
        r.raise_for_status()
        nodes.append(r.json()["data"]["node_numeric_id"])
    print(f"Đã đăng ký {gateway_id} với node {nodes}")
    return gateway_id, nodes


async def main() -> None:
    """Đọc tham số, đăng ký thiết bị rồi chạy các Gateway song song."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", default="http://localhost:8001", help="địa chỉ backend")
    p.add_argument("--gateways", type=int, default=1, help="số Gateway (bỏ qua khi có --gateway-id)")
    p.add_argument("--gateway-id", help="dùng Gateway có sẵn thay vì đăng ký mới")
    p.add_argument("--nodes", type=int, default=3, help="số node mỗi Gateway")
    p.add_argument("--interval", type=float, default=15, help="chu kỳ gửi của node (giây)")
    p.add_argument("--minutes", type=float, default=5, help="thời gian chạy (phút)")
    p.add_argument("--variant", choices=["gateway", "gateway-30pin"], default="gateway")
    p.add_argument("--offline-at", type=float, help="mất mạng sau N giây")
    p.add_argument("--offline-for", type=float, default=120, help="mất mạng trong N giây")
    p.add_argument("--resend-prob", type=float, default=0.0, help="xác suất gửi lại batch đã nhận 200")
    p.add_argument("--insecure", action="store_true", help="chấp nhận chứng chỉ tự ký (như firmware setInsecure)")
    args = p.parse_args()

    async with httpx.AsyncClient(verify=not args.insecure) as client:
        count = 1 if args.gateway_id else args.gateways
        setups = [await provision(args, client, i) for i in range(count)]
        await asyncio.gather(*(SimGateway(args, client, gw, nodes).run() for gw, nodes in setups))


if __name__ == "__main__":
    asyncio.run(main())
