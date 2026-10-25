"""Các tool tra cứu chất lượng không khí cho Xiaozhi (09-xiaozhi-mcp §4). Nạp bởi mcp_pipe.py.

Tool chỉ gọi API trợ lý của backend (/api/v1/assistant), không đọc DB, không lấy số liệu từ web.
Backend tính số liệu và câu `summary_vi`; Xiaozhi chỉ diễn đạt lại. Gọi API bằng urllib (thư viện chuẩn).

Biến môi trường:
- API_BASE: gốc API trợ lý, mặc định http://api:8000/api/v1/assistant (mạng Docker)
- ASSISTANT_TOKEN: token quyền assistant:read (không ghi vào log)
- API_TIMEOUT_S: thời gian chờ backend, mặc định 5 giây
"""

import json
import logging
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

log = logging.getLogger("aqi_tools")

DEFAULT_API_BASE = "http://api:8000/api/v1/assistant"
DEFAULT_TIMEOUT_S = 5.0

STATION_PARAM = {
    "type": "string",
    "description": "Mã trạm (vd ST001) hoặc tên trạm người dùng nói. Người dùng không nêu trạm thì để 'default'.",
    "default": "default",
}


def call_api(path: str, params: dict | None = None) -> dict:
    """GET một endpoint của API trợ lý, trả JSON.

    Backend trả lỗi có cấu trúc ({"ok": false, ...}) thì chuyển tiếp nguyên; không gọi được backend
    (mất kết nối, quá thời gian chờ, trả dữ liệu lạ) thì trả BACKEND_UNAVAILABLE.
    """
    base = os.environ.get("API_BASE", DEFAULT_API_BASE).rstrip("/")
    token = os.environ.get("ASSISTANT_TOKEN", "").strip()
    timeout = float(os.environ.get("API_TIMEOUT_S", DEFAULT_TIMEOUT_S))
    if not token:
        return unavailable("Bridge chưa được cấu hình ASSISTANT_TOKEN.")
    query = urlencode({k: v for k, v in (params or {}).items() if v is not None})
    request = Request(
        f"{base}{path}" + (f"?{query}" if query else ""),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as e:
        try:
            body = json.load(e)
        except ValueError:
            body = None
        if isinstance(body, dict) and body.get("ok") is False:
            return body
        return unavailable(f"Máy chủ dữ liệu trả lỗi {e.code}.")
    except (URLError, TimeoutError, OSError, ValueError):
        return unavailable("Không kết nối được tới máy chủ dữ liệu.")


def unavailable(message_vi: str) -> dict:
    """Lỗi khi không lấy được dữ liệu từ backend (chatbot báo không lấy được dữ liệu, không bịa số)."""
    return {"ok": False, "code": "BACKEND_UNAVAILABLE", "message_vi": message_vi}


def _station(args: dict) -> str:
    """Tham số trạm đã mã hóa để đặt vào đường dẫn; trống thì dùng trạm mặc định."""
    station = str(args.get("station") or "default").strip() or "default"
    return quote(station, safe="")


def _logged(name: str, fn):
    """Bọc tool: ghi log tên tool, tham số, mã kết quả và thời gian (không có token)."""

    def run(args: dict) -> dict:
        started = time.perf_counter()
        result = fn(args)
        ms = int((time.perf_counter() - started) * 1000)
        log.info("tool %s %s → %s (%d ms)", name, args, result.get("code", "ok"), ms)
        return result

    return run


def list_stations(_: dict) -> dict:
    """Danh sách trạm."""
    return call_api("/stations")


def get_current_air_quality(args: dict) -> dict:
    """Chất lượng không khí hiện tại của một trạm."""
    return call_api(f"/stations/{_station(args)}/current")


def get_history_summary(args: dict) -> dict:
    """Thống kê N giờ qua (1–72) của một trạm; backend kiểm tra số giờ."""
    return call_api(f"/stations/{_station(args)}/summary", {"hours": args.get("hours", 24)})


def get_forecast(args: dict) -> dict:
    """Dự báo AQI theo các mốc giờ; nhận "3,6,12" hoặc mảng [3, 6, 12]."""
    horizons = args.get("horizons")
    if isinstance(horizons, list):
        horizons = ",".join(str(h) for h in horizons)
    return call_api(f"/stations/{_station(args)}/forecast", {"horizons": horizons})


def register(server) -> None:
    """Đăng ký 4 tool với Xiaozhi: tên, mô tả tiếng Việt (khi nào gọi, đọc kết quả thế nào), schema tham số."""
    server.register_tool(
        "list_stations",
        "Liệt kê các trạm quan trắc không khí của hệ thống: mã trạm, tên, khu vực, trạm nào đang gửi dữ liệu và trạm "
        "mặc định. Gọi khi người dùng hỏi có những trạm nào, hoặc khi cần hỏi lại người dùng muốn xem trạm nào.",
        {"type": "object", "properties": {}},
        _logged("list_stations", list_stations),
    )
    server.register_tool(
        "get_current_air_quality",
        "CHỈ gọi khi người dùng hỏi về chất lượng không khí, bụi mịn, AQI, PM2.5, PM10 hoặc nhiệt độ, độ ẩm tại trạm "
        "quan trắc của hệ thống. Trả AQI Mỹ theo giờ (aqi, mức chất lượng của giờ đã đóng gần nhất), AQI tức thời "
        "của lần đo gần nhất (aqi_instant), PM2.5, PM10, nhiệt độ, độ ẩm và thời điểm đo. aqi null nghĩa là chưa có "
        "AQI giờ, không lấy AQI tức thời thay vào. Đọc theo summary_vi, nói rõ tên trạm, đơn vị và thời điểm; nếu "
        "stale là true phải báo dữ liệu đã cũ. "
        "Nếu ok là false thì đọc message_vi; nếu có danh sách trạm thì hỏi lại người dùng. Không tự bịa số.",
        {"type": "object", "properties": {"station": STATION_PARAM}},
        _logged("get_current_air_quality", get_current_air_quality),
    )
    server.register_tool(
        "get_history_summary",
        "Tóm tắt chất lượng không khí của một trạm trong N giờ qua (1 đến 72 giờ): AQI, PM2.5, PM10 trung bình, thấp "
        "nhất, cao nhất và xu hướng tăng/giảm; nhiệt độ, độ ẩm trung bình. Gọi khi người dùng hỏi về mấy giờ qua, "
        "hôm qua, gần đây không khí thay đổi ra sao. Đọc theo summary_vi. Không tự bịa số.",
        {
            "type": "object",
            "properties": {
                "station": STATION_PARAM,
                "hours": {"type": "integer", "minimum": 1, "maximum": 72, "default": 24, "description": "Số giờ"},
            },
        },
        _logged("get_history_summary", get_history_summary),
    )
    server.register_tool(
        "get_forecast",
        "Lấy dự báo AQI đã tính sẵn của một trạm cho các mốc giờ tới (bội số của 3, từ 3 đến 72 giờ; mặc định 3, 6, "
        "12, 24 giờ). Gọi khi người dùng hỏi sắp tới, mấy giờ nữa, ngày mai không khí thế nào. Đọc theo summary_vi, "
        "nói dự báo được tính lúc nào; status stale thì nói dự báo đã cũ bao nhiêu giờ; mốc confidence low chỉ là xu "
        "hướng. Nếu forecast là null (insufficient_history, no_data, error, unavailable) thì nói chưa có dự báo và lý "
        "do trong message_vi, tuyệt đối không tự đoán số.",
        {
            "type": "object",
            "properties": {
                "station": STATION_PARAM,
                "horizons": {
                    "type": "string",
                    "description": "Các mốc giờ cách nhau bằng dấu phẩy, vd '6' hoặc '3,6,12,24'",
                    "default": "3,6,12,24",
                },
            },
        },
        _logged("get_forecast", get_forecast),
    )
