async def test_healthz(client):
    r = await client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


async def test_readyz_checks_db_and_extensions(client):
    r = await client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["db"] == "ok"
    assert body["extensions"] == {"timescaledb": True, "postgis": True}


async def test_readyz_reports_model_status(client, db, model):
    """§11.10: kèm trạng thái model nhưng không báo lỗi khi chưa có model."""
    from app.modules.mlruntime.registry import registry

    body = (await client.get("/readyz")).json()
    assert body["model"]["status"] == "loaded" and body["model"]["dir_name"] == "v1-no_fill"
    registry._loaded = None
    r = await client.get("/readyz")
    assert r.status_code == 200 and r.json()["model"] == {"status": "not_loaded"}
