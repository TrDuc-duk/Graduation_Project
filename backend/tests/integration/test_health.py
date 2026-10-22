async def test_healthz(client):
    r = await client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


async def test_readyz_checks_db_and_extensions(client):
    r = await client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["db"] == "ok"
    assert body["extensions"] == {"timescaledb": True, "postgis": True}
