"""Nhật ký thao tác (D2, backend_design 11.8, 14.4): ghi cùng transaction, che dữ liệu nhạy cảm, lọc, phân trang."""

from datetime import timedelta

from app.core.db import get_sessionmaker, run_in_transaction
from app.modules.audit import service as audit
from tests.conftest import T0
from tests.fixtures.firmware import provision_gateway, provision_node
from tests.integration.helpers import rows


async def test_record_redacts_sensitive_values(db):
    changes = {"name": "Bách Khoa", "password": "abc", "nested": {"refresh_token": "t", "ok": 1},
               "list": [{"provision_key": "k"}]}  # fmt: skip
    await run_in_transaction(
        lambda s: audit.record(s, "node.update", user_id=None, username="admin", entity_type="node", entity_id=7,
                               changes=changes, ip="10.0.0.1")
    )  # fmt: skip
    [log] = rows(db, "SELECT * FROM audit_logs")
    assert (log.action, log.username, log.entity_type, log.entity_id, str(log.ip)) == (
        "node.update", "admin", "node", "7", "10.0.0.1",
    )  # fmt: skip
    assert log.changes == {"name": "Bách Khoa", "password": "***", "nested": {"refresh_token": "***", "ok": 1},
                           "list": [{"provision_key": "***"}]}  # fmt: skip


async def test_rollback_leaves_no_log(db):
    """Nghiệp vụ lỗi thì nhật ký cũng không còn (ghi chung transaction)."""
    async with get_sessionmaker()() as session:
        await session.begin()
        await audit.record(session, "node.retire", entity_type="node", entity_id=1)
        await session.rollback()
    assert rows(db, "SELECT * FROM audit_logs") == []


async def test_search_filters_and_pages(db):
    async def add(s):
        for i in range(5):
            await audit.record(s, "node.update" if i % 2 else "gateway.approve", entity_type="node", entity_id=i)

    await run_in_transaction(add)
    async with get_sessionmaker()() as s:
        items, total = await audit.search(s, page=1, page_size=2)
        assert total == 5 and len(items) == 2 and items[0].entity_id == "4"  # mới trước
        items, total = await audit.search(s, action="node.update")
        assert total == 2 and {i.entity_id for i in items} == {"1", "3"}
        _, total = await audit.search(s, start=T0 + timedelta(days=3650))
        assert total == 0


async def test_provisioning_is_audited_without_key(client, db):
    r = await client.post("/api/v1/provision/gateway", json=provision_gateway())
    assert r.status_code == 201
    gw = r.json()["data"]["id"]
    await client.post("/api/v1/provision/node", json=provision_node(gateway_id=None))
    logs = rows(db, "SELECT action, username, entity_type, entity_id, changes FROM audit_logs ORDER BY id")
    assert [(lg.action, lg.username, lg.entity_type) for lg in logs] == [
        ("gateway.provision", "provisioning", "gateway"), ("node.provision", "provisioning", "node"),
    ]  # fmt: skip
    assert logs[0].entity_id == gw and logs[0].changes["status"] == "pending"
    assert logs[1].changes["station_code"] == "ST001" and logs[1].changes["device_code"] == "NODE_001"
    assert all("provision_key" not in lg.changes and "airquality" not in str(lg.changes) for lg in logs)
