"""Payload đúng như firmware datn-main gửi (chưa có dữ liệu thật).

Nguồn: datn-main/firmware/gateway/src/net/http_client.cpp (bản `gateway`, có msg_id),
bản `gateway-30pin` bỏ msg_id; datn-main/scripts/simulator.js; captive_portal.cpp của Gateway và node.
"""

SECRET = "super-secret-key"
PROVISION_KEY = "airquality2026"


def item(node: int = 1, msg_id: int | None = 12, **values: object) -> dict:
    """Một gói dữ liệu node như Gateway gửi: PM/nhiệt/ẩm là float (x/10.0f), co2/tvoc/battery là số nguyên, rssi = 0."""
    data = {
        "node_id": f"NODE_{node:03d}",
        "pm25": 70.0,
        "pm10": 80.5,
        "co2": 800,
        "tvoc": 120,
        "temperature": 32.5,
        "humidity": 70.0,
        "battery": 92,
        "rssi": 0,
    }
    if msg_id is not None:  # bản gateway-30pin không gửi msg_id
        data["msg_id"] = msg_id
    data.update(values)
    return data


def heartbeat_item(node: int = 1, msg_id: int | None = 13, battery: int = 90) -> dict:
    """Heartbeat node (pktType 0x02) bị Gateway chuyển tiếp như dữ liệu: mọi số đo = 0."""
    return item(node, msg_id, pm25=0.0, pm10=0.0, co2=0, tvoc=0, temperature=0.0, humidity=0.0, battery=battery)


def sensor_error_item(node: int = 1, msg_id: int | None = 14) -> dict:
    """Cảm biến lỗi: PMS/DHT gửi null (0xFFFF/0x7FFF), CCS811 lỗi gửi 65535."""
    return item(node, msg_id, pm25=None, pm10=None, temperature=None, humidity=None, co2=65535, tvoc=65535)


def telemetry(gateway_id: str = "GW_001", items: list[dict] | None = None, secret: str = SECRET) -> dict:
    """Body POST /api/v1/telemetry."""
    return {"gateway_id": gateway_id, "secret": secret, "data": items if items is not None else [item()]}


def heartbeat(gateway_id: str = "GW_001", secret: str = SECRET) -> dict:
    """Body POST /api/v1/telemetry/heartbeat (gửi mỗi 5 phút)."""
    return {"gateway_id": gateway_id, "secret": secret}


def provision_gateway(name: str = "Gateway Bách Khoa", location_desc: str = "Tầng 3 nhà C1") -> dict:
    """Body cổng cấu hình Gateway gửi khi đăng ký."""
    return {"provision_key": PROVISION_KEY, "name": name, "location_desc": location_desc}


def provision_node(name: str = "Sensor Hà Nội", gateway_id: str | None = "GW_001", **coords: float) -> dict:
    """Body cổng cấu hình node gửi khi đăng ký (lat/lng tùy chọn)."""
    body = {"provision_key": PROVISION_KEY, "name": name, **coords}
    if gateway_id is not None:
        body["gateway_id"] = gateway_id
    return body
