# xiaozhi-bridge

Cầu nối giữa chatbot Xiaozhi (dịch vụ có sẵn) và API trợ lý của backend. Thiết kế: 09-xiaozhi-mcp (tài liệu nội bộ).

```text
Người dùng → Xiaozhi ⇄ (WebSocket MCP, bridge chủ động mở) ⇄ xiaozhi-bridge → HTTP + Bearer → /api/v1/assistant/* → DB
```

- `mcp_pipe.py` nối tới `MCP_ENDPOINT` và trả lời các lệnh MCP của Xiaozhi (`initialize`, `tools/list`, `tools/call`, `ping`). Mất kết nối thì tự nối lại, chờ 1, 2, 4, … tối đa 600 giây.
- `aqi_tools.py` đăng ký 4 tool, mỗi tool có tên, mô tả tiếng Việt và schema tham số, giống cách `registerTool` trong [docs/xiaozhi.h](../docs/xiaozhi.h). Tool chỉ gọi API, không đọc DB.
- Chỉ dùng một thư viện ngoài là `websockets`. Gọi HTTP bằng `urllib` của Python.

## Tool

| Tool | API | Khi nào Xiaozhi gọi |
|---|---|---|
| `list_stations()` | `GET /stations` | Hỏi có những trạm nào, hoặc cần hỏi lại trạm |
| `get_current_air_quality(station="default")` | `GET /stations/{ref}/current` | Hỏi không khí, AQI, PM2.5, PM10, nhiệt độ, độ ẩm hiện tại |
| `get_history_summary(station="default", hours=24)` | `GET /stations/{ref}/summary?hours=` | Hỏi mấy giờ qua thay đổi ra sao (1–72 giờ) |
| `get_forecast(station="default", horizons="3,6,12,24")` | `GET /stations/{ref}/forecast?horizons=` | Hỏi sắp tới thế nào (mốc bội 3, từ 3 đến 72 giờ) |

- `station` nhận mã trạm (`ST001`), tên trạm (không phân biệt dấu) hoặc `default`. Nếu người dùng không nêu trạm, bridge gửi `default` và backend dùng trạm mặc định.
- Kết quả là JSON do backend tạo, có `summary_vi`. Khi có lỗi, kết quả có dạng `{"ok": false, "code", "message_vi"}`.
- Khi không gọi được backend (mất kết nối, quá 5 giây, trả lỗi lạ), bridge tự trả `BACKEND_UNAVAILABLE`.

## Cấu hình

| Biến | Ý nghĩa |
|---|---|
| `MCP_ENDPOINT` | URL WebSocket kèm token, lấy trên console Xiaozhi (mục MCP endpoint / "MCP 接入点"). **Bí mật**: chỉ đặt trong `docker/.env`, không commit. Bridge chỉ ghi tên host vào log |
| `ASSISTANT_TOKEN` | Token của API trợ lý, quyền `assistant:read`. Phải **trùng** giá trị mà container `api` đang dùng. Tạo bằng `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Không ghi vào log |
| `API_BASE` | Mặc định `http://api:8000/api/v1/assistant` (trong mạng Docker). Nginx không định tuyến nhóm API này ra Internet |
| `API_TIMEOUT_S` | Thời gian chờ backend, mặc định 5 giây |

## Chạy

Qua Docker Compose (cách khuyên dùng):

```bash
cd docker
# 1. Điền ASSISTANT_TOKEN và MCP_ENDPOINT trong docker/.env
# 2. Khởi động lại api để bật API trợ lý (api chỉ gắn /api/v1/assistant khi có token)
docker compose -f docker-compose.dev.yml up -d api
# 3. Chạy bridge
docker compose -f docker-compose.dev.yml --profile xiaozhi up -d --build xiaozhi-bridge
docker compose -f docker-compose.dev.yml logs -f xiaozhi-bridge
```

Chạy trực tiếp trên máy (backend ở cổng 8001 của máy dev):

```bash
cd xiaozhi-bridge
python -m venv .venv && .venv/bin/pip install -r requirements.txt
API_BASE=http://127.0.0.1:8001/api/v1/assistant ASSISTANT_TOKEN=... MCP_ENDPOINT='wss://...' \
  .venv/bin/python mcp_pipe.py aqi_tools.py
```

Trạm phải được duyệt mới xuất hiện với chatbot. Khi chưa có Admin (M4), duyệt trạm và đặt trạm mặc định bằng lệnh sau, chạy trong `backend/`:

```bash
python -m scripts.set_station --code ST001 --name "Tên trạm" --district "Quận" --lat <vĩ độ> --lng <kinh độ> --activate --default
```

## Kiểm tra

1. Log bridge có dòng `Đã kết nối MCP endpoint <host>, 4 tool`.
2. Trên console Xiaozhi, mục MCP endpoint hiện trạng thái đã kết nối và danh sách 4 tool.
3. Hỏi loa:
   - "Chất lượng không khí ở trạm ST001 hiện tại thế nào?" → `get_current_air_quality`
   - "24 giờ qua AQI thay đổi ra sao?" → `get_history_summary`
   - "6 giờ tới có dự báo không?" → `get_forecast` (hiện trả "chưa có dự báo")
4. Mỗi lần gọi có một dòng `tool …` trong log bridge, một dòng `assistant …` trong log api, và một dòng trong bảng `assistant_calls`.

Test (chỉ cần thư viện chuẩn; nếu đã cài `websockets` thì chạy thêm test vòng kết nối WebSocket):

```bash
cd xiaozhi-bridge && python -m unittest discover -s tests -v
```
