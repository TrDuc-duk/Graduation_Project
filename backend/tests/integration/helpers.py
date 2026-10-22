"""Hàm tiện ích cho test integration: đọc/ghi DB trực tiếp bằng engine của aqi_migrator."""

from sqlalchemy import text


def rows(engine, sql: str, **params):
    """Chạy SELECT và trả mọi dòng."""
    with engine.connect() as conn:
        return conn.execute(text(sql), params).all()


def scalar(engine, sql: str, **params):
    """Chạy SELECT và trả một giá trị."""
    with engine.connect() as conn:
        return conn.scalar(text(sql), params)


def execute(engine, sql: str, **params) -> None:
    """Chạy lệnh ghi và commit."""
    with engine.begin() as conn:
        conn.execute(text(sql), params)


def add_gateway(engine, gateway_id: str = "GW_001", status: str = "active", **cols) -> None:
    """Thêm Gateway trực tiếp vào DB (thay cho bước Admin duyệt, thuộc M4)."""
    values = {"id": gateway_id, "status": status, "registered_via": "admin", "name": gateway_id, **cols}
    names = ", ".join(values)
    marks = ", ".join(f":{k}" for k in values)
    execute(engine, f"INSERT INTO gateways (lora_network_id, {names}) VALUES (1, {marks})", **values)


def add_node(engine, addr: int, status: str = "active", **cols) -> int:
    """Thêm node trực tiếp vào DB; trả nodes.id."""
    values = {"lora_addr": addr, "status": status, "registered_via": "admin", "name": f"Node {addr}", **cols}
    names = ", ".join(values)
    marks = ", ".join(f":{k}" for k in values)
    with engine.begin() as conn:
        n = conn.scalar(text("SELECT nextval('station_code_seq')"))
        return conn.scalar(
            text(f"INSERT INTO nodes (station_code, lora_network_id, {names}) VALUES (:code, 1, {marks}) RETURNING id"),
            {"code": f"ST{n:03d}", **values},
        )
