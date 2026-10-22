"""Test bridge Xiaozhi bằng thư viện chuẩn: python -m unittest discover -s tests (chạy trong thư mục xiaozhi-bridge).

- Backend giả (http.server) để kiểm tra URL, header, chuyển tiếp lỗi, timeout, mất kết nối.
- Lệnh MCP (initialize, tools/list, tools/call, ping) gọi thẳng McpServer.handle.
- Vòng kết nối WebSocket thật với một "Xiaozhi" giả cục bộ (bỏ qua nếu chưa cài websockets).
"""

import asyncio
import json
import os
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aqi_tools  # noqa: E402
from mcp_pipe import McpServer, load_tools  # noqa: E402

TOKEN = "bridge-test-token"
CURRENT = {"ok": True, "station": {"code": "ST001", "name": "Bách Khoa"}, "aqi": 119, "summary_vi": "AQI 119"}
NOT_FOUND = {"ok": False, "code": "STATION_NOT_FOUND", "message_vi": "Không tìm thấy trạm", "stations": []}


class FakeBackend(BaseHTTPRequestHandler):
    """API trợ lý giả: ghi lại request, trả theo đường dẫn."""

    requests: list[tuple[str, str | None]] = []

    def do_GET(self):  # noqa: N802 (tên do http.server quy định)
        FakeBackend.requests.append((self.path, self.headers.get("Authorization")))
        if self.path.startswith("/api/v1/assistant/slow"):
            time.sleep(1.5)
            return self._send(200, {"ok": True})
        if self.path.startswith("/api/v1/assistant/broken"):
            return self._send(500, "Internal Server Error", raw=True)
        if self.path.endswith("/current") and ("ST001" in self.path or "B%C3%A1ch" in self.path):
            return self._send(200, CURRENT)
        if "/forecast" in self.path or "/summary" in self.path:
            return self._send(200, {"ok": True, "path": self.path})
        return self._send(404, NOT_FOUND)

    def _send(self, status: int, body, raw: bool = False):
        data = body.encode() if raw else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/plain" if raw else "application/json")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_):
        pass


class BridgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.http = ThreadingHTTPServer(("127.0.0.1", 0), FakeBackend)
        threading.Thread(target=cls.http.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.http.server_port}/api/v1/assistant"
        cls.server = McpServer("aqi-monitor")
        load_tools(str(Path(__file__).resolve().parents[1] / "aqi_tools.py"), cls.server)

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()

    def setUp(self):
        FakeBackend.requests.clear()
        os.environ.update(API_BASE=self.base, ASSISTANT_TOKEN=TOKEN, API_TIMEOUT_S="5")

    def call(self, name: str, arguments: dict | None = None) -> tuple[dict, bool]:
        """tools/call qua McpServer, trả (JSON trong khối text, isError)."""
        reply = self.server.handle(
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": name, "arguments": arguments or {}}}
        )
        result = reply["result"]
        return json.loads(result["content"][0]["text"]), result["isError"]

    # ---------- giao thức MCP ----------

    def test_initialize_and_ping(self):
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}}
        reply = self.server.handle(init)
        self.assertEqual(reply["result"]["protocolVersion"], "2024-11-05")
        self.assertIn("tools", reply["result"]["capabilities"])
        self.assertIsNone(self.server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        self.assertEqual(self.server.handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"], {})

    def test_tools_list_has_four_tools_with_schema(self):
        tools = self.server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/list"})["result"]["tools"]
        self.assertEqual(
            [t["name"] for t in tools],
            ["list_stations", "get_current_air_quality", "get_history_summary", "get_forecast"],
        )
        for t in tools:
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertTrue(t["description"])

    def test_unknown_method_and_tool(self):
        reply = self.server.handle({"jsonrpc": "2.0", "id": 4, "method": "resources/list"})
        self.assertEqual(reply["error"]["code"], -32601)
        data, is_error = self.call("delete_everything")
        self.assertEqual((data["code"], is_error), ("UNKNOWN_TOOL", True))

    # ---------- gọi API trợ lý ----------

    def test_current_calls_api_with_bearer_token(self):
        data, is_error = self.call("get_current_air_quality", {"station": "ST001"})
        self.assertEqual((data, is_error), (CURRENT, False))
        self.assertEqual(FakeBackend.requests, [("/api/v1/assistant/stations/ST001/current", f"Bearer {TOKEN}")])

    def test_station_name_is_url_encoded_and_default_used(self):
        self.call("get_current_air_quality", {"station": "Bách Khoa"})
        self.call("get_current_air_quality", {})
        paths = [p for p, _ in FakeBackend.requests]
        self.assertEqual(paths[0], "/api/v1/assistant/stations/B%C3%A1ch%20Khoa/current")
        self.assertEqual(paths[1], "/api/v1/assistant/stations/default/current")

    def test_summary_and_forecast_params(self):
        self.call("get_history_summary", {"station": "ST001", "hours": 6})
        self.call("get_forecast", {"station": "ST001", "horizons": [3, 6]})
        self.call("get_forecast", {"station": "ST001"})
        paths = [p for p, _ in FakeBackend.requests]
        self.assertEqual(paths[0], "/api/v1/assistant/stations/ST001/summary?hours=6")
        self.assertEqual(paths[1], "/api/v1/assistant/stations/ST001/forecast?horizons=3%2C6")
        self.assertEqual(paths[2], "/api/v1/assistant/stations/ST001/forecast")

    def test_backend_error_is_forwarded(self):
        data, is_error = self.call("get_current_air_quality", {"station": "XYZ"})
        self.assertEqual((data, is_error), (NOT_FOUND, True))

    def test_timeout_and_bad_response_become_backend_unavailable(self):
        os.environ["API_TIMEOUT_S"] = "0.3"
        self.assertEqual(aqi_tools.call_api("/slow")["code"], "BACKEND_UNAVAILABLE")
        self.assertEqual(aqi_tools.call_api("/broken")["code"], "BACKEND_UNAVAILABLE")

    def test_backend_down_or_token_missing(self):
        os.environ["API_BASE"] = "http://127.0.0.1:9/api/v1/assistant"  # cổng không có dịch vụ
        data, is_error = self.call("list_stations")
        self.assertEqual((data["code"], is_error), ("BACKEND_UNAVAILABLE", True))
        os.environ["ASSISTANT_TOKEN"] = ""
        self.assertIn("ASSISTANT_TOKEN", aqi_tools.call_api("/stations")["message_vi"])

    def test_token_never_logged(self):
        with self.assertLogs("aqi_tools", level="INFO") as logs:
            self.call("get_current_air_quality", {"station": "ST001"})
        self.assertNotIn(TOKEN, "\n".join(logs.output))


try:
    from websockets.asyncio.server import serve as ws_serve
except ImportError:  # chưa cài websockets: chỉ chạy các test trên
    ws_serve = None


@unittest.skipIf(ws_serve is None, "chưa cài websockets")
class WebSocketLoopTest(unittest.TestCase):
    """Bridge chủ động nối tới "Xiaozhi" giả, trả lời initialize, tools/list; URL có token không bị ghi log."""

    def test_serve_answers_over_websocket(self):
        async def scenario():
            replies: list[dict] = []
            done = asyncio.Event()

            async def xiaozhi(ws):
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}))
                replies.append(json.loads(await ws.recv()))
                await ws.send(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))
                await ws.send(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}))
                replies.append(json.loads(await ws.recv()))
                done.set()

            server = McpServer("aqi-monitor")
            load_tools(str(Path(__file__).resolve().parents[1] / "aqi_tools.py"), server)
            async with ws_serve(xiaozhi, "127.0.0.1", 0) as ws_server:
                port = ws_server.sockets[0].getsockname()[1]
                with self.assertLogs("mcp_pipe", level="INFO") as logs:
                    task = asyncio.create_task(server.serve(f"ws://127.0.0.1:{port}/mcp/?token=secret-endpoint-token"))
                    await asyncio.wait_for(done.wait(), 5)
                    task.cancel()
            self.assertEqual([r["id"] for r in replies], [1, 2])
            self.assertEqual(len(replies[1]["result"]["tools"]), 4)
            self.assertNotIn("secret-endpoint-token", "\n".join(logs.output))

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
