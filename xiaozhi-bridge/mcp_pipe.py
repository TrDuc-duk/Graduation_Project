"""Nối tới MCP endpoint của Xiaozhi và phục vụ các tool đăng ký trong một file (vd aqi_tools.py).

Chạy: MCP_ENDPOINT=wss://... python mcp_pipe.py aqi_tools.py

Cách làm giống mẫu ESP32 docs/xiaozhi.h (WebSocketMCP.registerTool) và mẫu 78/mcp-calculator:
bridge CHỦ ĐỘNG mở WebSocket tới Xiaozhi, mỗi message là một JSON-RPC 2.0 của giao thức MCP.
Ở đây xử lý trực tiếp các lệnh Xiaozhi dùng (initialize, tools/list, tools/call, ping) nên chỉ cần thư viện
`websockets`, không cần MCP SDK. Mất kết nối thì tự nối lại, chờ 1, 2, 4, … tối đa 600 giây.
"""

import asyncio
import importlib.util
import json
import logging
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

log = logging.getLogger("mcp_pipe")

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")  # bản giao thức MCP hỗ trợ (chỉ dùng tools)
INITIAL_BACKOFF_S = 1
MAX_BACKOFF_S = 600


@dataclass
class Tool:
    """Một tool: tên, mô tả cho LLM, JSON Schema tham số và hàm xử lý nhận dict tham số, trả dict JSON."""

    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict], dict]


class McpServer:
    """MCP server tối giản chỉ có tools (tương ứng WebSocketMCP trong docs/xiaozhi.h)."""

    def __init__(self, name: str, version: str = "1.0.0"):
        self.name = name
        self.version = version
        self.tools: dict[str, Tool] = {}

    def register_tool(self, name: str, description: str, input_schema: dict, handler: Callable[[dict], dict]) -> None:
        """Đăng ký một tool (như mcpClient.registerTool(tên, mô tả, schema, callback) trong mẫu C++)."""
        self.tools[name] = Tool(name, description, input_schema, handler)

    def handle(self, message: dict) -> dict | None:
        """Xử lý một JSON-RPC; trả response, hoặc None với notification (không có id)."""
        method, msg_id = message.get("method"), message.get("id")
        if msg_id is None:
            return None  # notification, vd notifications/initialized
        params = message.get("params") or {}
        if method == "initialize":
            requested = params.get("protocolVersion")
            result = {
                "protocolVersion": requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[-1],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": self.name, "version": self.version},
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {
                "tools": [
                    {"name": t.name, "description": t.description, "inputSchema": t.input_schema}
                    for t in self.tools.values()
                ]
            }
        elif method == "tools/call":
            result = self._call_tool(params.get("name"), params.get("arguments") or {})
        else:
            return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"Không hỗ trợ {method}"}}
        return {"jsonrpc": "2.0", "id": msg_id, "result": result}

    def _call_tool(self, name: str | None, arguments: dict) -> dict:
        """Gọi tool, trả kết quả dạng text JSON; tool lạ hoặc lỗi bất ngờ thì isError=true kèm thông báo."""
        tool = self.tools.get(name or "")
        if tool is None:
            return _text_result({"ok": False, "code": "UNKNOWN_TOOL", "message_vi": f"Không có tool {name}."}, True)
        try:
            data = tool.handler(arguments)
        except Exception:
            log.exception("Tool %s lỗi", name)
            data = {"ok": False, "code": "BRIDGE_ERROR", "message_vi": "Bridge gặp lỗi khi xử lý yêu cầu."}
        return _text_result(data, is_error=not data.get("ok", False))

    async def serve(self, endpoint: str) -> None:
        """Giữ kết nối tới Xiaozhi mãi mãi: nối, phục vụ, mất kết nối thì chờ tăng dần rồi nối lại."""
        from websockets.asyncio.client import connect  # thư viện ngoài duy nhất của bridge

        backoff = INITIAL_BACKOFF_S
        host = urlsplit(endpoint).netloc  # chỉ ghi host: URL endpoint chứa token
        while True:
            try:
                async with connect(endpoint) as ws:
                    log.info("Đã kết nối MCP endpoint %s, %d tool", host, len(self.tools))
                    backoff = INITIAL_BACKOFF_S
                    async for raw in ws:
                        for reply in await self._replies(raw):
                            await ws.send(json.dumps(reply, ensure_ascii=False))
                            result = reply.get("result", {})
                            if "tools" in result:
                                log.info("Đã trả tools/list cho Xiaozhi: %s", ", ".join(t["name"] for t in result["tools"]))
                            elif "protocolVersion" in result:
                                log.info("Đã trả initialize cho Xiaozhi (%s)", result["protocolVersion"])
            except Exception as e:  # mất mạng, endpoint đóng kết nối, token sai…
                log.warning("Mất kết nối MCP endpoint %s (%s); thử lại sau %d giây", host, type(e).__name__, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF_S)

    async def _replies(self, raw: str | bytes) -> list[dict]:
        """Các response cho một message (một lệnh hoặc mảng lệnh); tool chạy ở thread riêng để không chặn kết nối."""
        try:
            message = json.loads(raw)
        except ValueError:
            return [{"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON không hợp lệ"}}]
        batch = message if isinstance(message, list) else [message]
        replies = [await asyncio.to_thread(self.handle, m) for m in batch if isinstance(m, dict)]
        return [r for r in replies if r is not None]


def _text_result(data: dict, is_error: bool) -> dict:
    """Kết quả tools/call: một khối text chứa JSON (LLM của Xiaozhi đọc và diễn đạt lại)."""
    return {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}], "isError": is_error}


def load_tools(path: str, server: McpServer) -> None:
    """Nạp file tool (vd aqi_tools.py) và gọi hàm `register(server)` trong file đó."""
    spec = importlib.util.spec_from_file_location("tools", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.register(server)


def main() -> None:
    """Đọc MCP_ENDPOINT, nạp tool từ file ở tham số dòng lệnh rồi giữ kết nối tới Xiaozhi."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if len(sys.argv) != 2:
        sys.exit("Cách dùng: python mcp_pipe.py aqi_tools.py")
    endpoint = os.environ.get("MCP_ENDPOINT", "").strip()
    if not endpoint:
        sys.exit("Thiếu MCP_ENDPOINT (lấy trên console Xiaozhi).")
    server = McpServer("aqi-monitor")
    load_tools(sys.argv[1], server)
    asyncio.run(server.serve(endpoint))


if __name__ == "__main__":
    main()
