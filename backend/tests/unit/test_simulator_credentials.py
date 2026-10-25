"""Mô phỏng phải dùng khóa được cấu hình và dừng trước I/O khi chưa có khóa."""

import argparse
import json
import sys

import httpx
import pytest

from scripts import simulate_gateway


async def test_missing_credentials_stops_before_network(monkeypatch):
    """Không âm thầm gửi khóa mặc định khi người dùng quên cấu hình."""
    for name in ("GATEWAY_SECRET", "GATEWAY_SECRETS", "PROVISION_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(sys, "argv", ["simulate_gateway.py"])

    def unexpected_client(*args, **kwargs):
        raise AssertionError("Không được tạo HTTP client khi thiếu khóa")

    monkeypatch.setattr(simulate_gateway.httpx, "AsyncClient", unexpected_client)
    with pytest.raises(SystemExit) as exc:
        await simulate_gateway.main()
    assert exc.value.code == 2


async def test_requests_use_supplied_credentials():
    """Provision và telemetry sử dụng khóa riêng do người chạy cung cấp."""
    requests = []

    def handle(request):
        payload = json.loads(request.content)
        requests.append((request.url.path, payload))
        if request.url.path.endswith("/provision/gateway"):
            return httpx.Response(201, json={"data": {"id": "GW_001"}})
        if request.url.path.endswith("/provision/node"):
            return httpx.Response(201, json={"data": {"node_numeric_id": 1}})
        return httpx.Response(200, json={"success": True})

    args = argparse.Namespace(
        base="http://test",
        gateway_id=None,
        nodes=1,
        gateway_secret="fake-telemetry-credential",
        provision_key="fake-provision-credential",
        resend_prob=0,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        gateway, nodes = await simulate_gateway.provision(args, client, 0)
        simulator = simulate_gateway.SimGateway(args, client, gateway, nodes)
        simulator.buffer.append({"node_id": "NODE_001"})
        await simulator.flush()

    assert len(requests) == 3
    assert all(payload["provision_key"] == args.provision_key for _, payload in requests[:2])
    assert requests[2][1]["secret"] == args.gateway_secret
    assert simulator.buffer == []
