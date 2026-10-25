from pathlib import Path

import pytest

MODELS = Path(__file__).resolve().parents[3] / "models" / "xgb"  # bundle tạo bằng scripts.prepare_model_bundle


@pytest.fixture(autouse=True)
def _clean_db(db):
    """Mọi test integration chạy trên DB sạch."""
    return db


@pytest.fixture
async def live_server(db):
    """Chạy ứng dụng thật (Uvicorn, có lifespan: EventHub LISTEN) trên cổng ngẫu nhiên; trả gốc URL."""
    import asyncio

    import uvicorn

    from app.core import events
    from app.main import create_app
    from app.modules.realtime.router import clear_public_cache

    clear_public_cache()
    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=0, log_level="warning"))
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    await asyncio.wait_for(events.hub.connected.wait(), 5)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await asyncio.wait_for(task, 5)


@pytest.fixture
async def model(db, monkeypatch):
    """Model v1-no_fill active trong registry dùng chung của tiến trình; dọn trạng thái nạp sau test."""
    from app.core.config import get_settings
    from app.modules.mlruntime.registry import registry

    monkeypatch.setenv("MODEL_DIR", str(MODELS))
    get_settings.cache_clear()
    await registry.rescan()
    yield registry.current()
    registry._loaded = None
    get_settings.cache_clear()
