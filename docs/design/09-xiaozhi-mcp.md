# 09 — Tích hợp chatbot Xiaozhi qua MCP endpoint

**Trạng thái:** nháp. Phạm vi và kiến trúc tích hợp đã chốt (04/10/2026). Endpoint đã liệt kê ở [backend_design §11.9](backend_design.md#119-trợ-lý-xiaozhi); response dùng lại dữ liệu của API công khai (§11.3–11.5) và dự báo (§8).
**Cập nhật:** 04/10/2026

---

## 1. Quyết định đã chốt

| Mã | Quyết định |
|---|---|
| X1 | Dùng chatbot Xiaozhi **có sẵn**, kết nối qua **MCP endpoint**. Không tự host Xiaozhi server (không cần quan tâm ASR/TTS/LLM, không tốn RAM VPS). |
| X2 | Chatbot **chỉ tra cứu thông tin môi trường và dự báo**. Không trả lời thông tin quản trị: pin, cảnh báo, Gateway, người dùng, cấu hình, log. |
| X3 | Hàm MCP **không đọc DB trực tiếp** và **không lấy dữ liệu từ trang web**. Hàm MCP gọi một nhóm API riêng, chỉ đọc: `/api/v1/assistant/*`. |
| X4 | Mã đăng ký hàm chạy trong container riêng `xiaozhi-bridge`, cùng Docker Compose với backend. Bridge không chứa logic nghiệp vụ. |

X3 và X4 là đề xuất trong trao đổi ngày 04/10/2026, bạn không phản đối khi chốt X1, X2. Nếu muốn đổi, chỉ cần sửa mục này.

---

## 2. Cách MCP endpoint hoạt động

Theo mã mẫu chính thức [78/mcp-calculator](https://github.com/78/mcp-calculator):

- Hàm được khai báo bằng Python MCP SDK (`FastMCP`, decorator `@mcp.tool()`), chạy như một MCP server qua **stdio**.
- Script `mcp_pipe.py` đọc biến môi trường `MCP_ENDPOINT` (URL WebSocket kèm token, lấy từ console Xiaozhi), **chủ động mở WebSocket** tới Xiaozhi, rồi chuyển tiếp dữ liệu giữa WebSocket và stdin/stdout của MCP server.
- Mất kết nối thì `mcp_pipe.py` tự kết nối lại với thời gian chờ tăng dần (1 giây, tối đa 600 giây).

Hệ quả: kết nối đi **từ phía mình ra ngoài**. Backend không phải mở cổng nào cho Xiaozhi, API trợ lý chỉ cần nằm trong mạng nội bộ Docker.

```text
Người dùng nói ──▶ Loa Xiaozhi ⇄ Xiaozhi server (ASR → LLM → TTS)
                                        ▲
                                        │ WebSocket (MCP_ENDPOINT), bridge chủ động mở
                         ┌──────────────┴───────────────┐
                         │ xiaozhi-bridge               │
                         │  mcp_pipe.py                 │
                         │  aqi_tools.py (@mcp.tool())  │
                         └──────────────┬───────────────┘
                                        │ HTTP nội bộ Docker, token chỉ đọc
                         ┌──────────────▼───────────────┐
                         │ FastAPI /api/v1/assistant/*  │
                         │  → service dùng chung với web │
                         └──────────────┬───────────────┘
                                        ▼
                                   PostgreSQL
```

---

## 3. Vì sao cần API riêng cho trợ lý

| Phương án | Đánh giá |
|---|---|
| Hàm MCP query thẳng DB | **Loại.** Phải viết lại logic mức AQI, ngưỡng "dữ liệu cũ", phân biệt AQI giờ/AQI tức thời, độ tin cậy dự báo → chatbot dễ nói khác web. Phải giao mật khẩu DB cho tiến trình bot. Đổi schema là bot hỏng. Không giới hạn được phạm vi dữ liệu (X2). |
| Lấy từ trang web | **Loại.** Web là SPA, HTML không chứa số liệu. |
| Gọi nguyên API công khai của web | Dùng được nhưng không tối ưu: response thiết kế để vẽ biểu đồ (nhiều điểm, nhiều trường), LLM tốn token, chậm, dễ đọc sai; thiếu nhãn tiếng Việt và thời gian tương đối. |
| **API trợ lý riêng** | **Chọn.** Mỗi endpoint khớp một hàm MCP; response gọn, backend tính sẵn mức AQI, xu hướng, câu tóm tắt; chỉ trả dữ liệu thuộc phạm vi X2. Gọi cùng service với API web nên số liệu luôn khớp. |

Phương án chạy hàm MCP ngay trong tiến trình FastAPI cũng bị loại: vòng kết nối lại tới Xiaozhi (có lúc chờ tới 10 phút) và tiến trình con của `mcp_pipe` không nên gắn với vòng đời của API nhận dữ liệu cảm biến.

---

## 4. Danh sách hàm (bản nháp)

| Hàm MCP | Endpoint | Nội dung trả về |
|---|---|---|
| `list_stations()` | `GET /api/v1/assistant/stations` | Mã, tên, khu vực, trạm có đang gửi dữ liệu không. Giúp LLM hiểu "trạm Bách Khoa" là trạm nào. |
| `get_current_air_quality(station)` | `GET /api/v1/assistant/stations/{ref}/current` | AQI, mức AQI (tiếng Việt), PM2.5, PM10, nhiệt độ, độ ẩm, thời điểm đo, số phút từ lúc đo, cờ dữ liệu cũ, khuyến nghị sức khỏe, câu tóm tắt. |
| `get_forecast(station, horizons?)` | `GET /api/v1/assistant/stations/{ref}/forecast` | AQI dự báo theo mốc (mọi mốc 3–72 giờ, P6; không nêu mốc thì trả 3, 6, 12, 24 giờ cho câu trả lời ngắn), mức AQI, nhãn độ tin cậy, thời điểm dữ liệu đầu vào, thời điểm đích. Không có dự báo thì nêu lý do (vd. "còn thiếu 18 giờ dữ liệu"). Dự báo cũ (`status: stale`, backend_design 11.5) thì nói rõ "dự báo được tính lúc …, cách đây X giờ" và chỉ đọc các mốc còn ở tương lai. |
| `get_history_summary(station, hours)` | `GET /api/v1/assistant/stations/{ref}/summary?hours=` | Trung bình, cao nhất, thấp nhất, xu hướng tăng/giảm trong tối đa 72 giờ. Không trả cả chuỗi số. |
| `explain_metric(metric)` | Không cần gọi backend | Giải thích AQI, PM2.5, PM10 bằng nội dung soạn sẵn trong bridge. |

`get_system_status` trong bản nháp trao đổi trước **bị bỏ** theo X2. Trạng thái "trạm đang không gửi dữ liệu" vẫn được trả trong `list_stations` và `current`, vì nó cho biết số liệu môi trường có còn mới hay không; không kèm pin, Gateway hay cảnh báo.

Ví dụ response của `current` (minh họa định dạng, cùng trường với [backend_design §11.3](backend_design.md#113-công-khai-web)):

```json
{
  "ok": true,
  "station": {"id": "ST001", "name": "Bách Khoa"},
  "aqi": 142,
  "aqi_kind": "hourly",
  "level": "Không tốt cho nhóm nhạy cảm",
  "pm25": 52.4, "pm10": 68.0, "temperature": 29.1, "humidity": 78,
  "measured_at": "2026-10-04T14:00:00+07:00",
  "age_minutes": 12,
  "stale": false,
  "summary_vi": "AQI 142, nhóm nhạy cảm nên hạn chế ra ngoài."
}
```

---

## 5. Quy tắc thiết kế API trợ lý

1. **Chỉ đọc, chỉ dữ liệu môi trường và dự báo** (X2). Không có endpoint ghi; không trả trường quản trị.
2. **Số liệu do backend tính**, LLM chỉ diễn đạt. Mọi response có số liệu đều kèm trạm và thời điểm đo hoặc thời điểm dự báo.
3. **Dùng chung service với API web**: cùng trạm, cùng thời điểm thì cùng con số (tiêu chí nghiệm thu trong ARCHITECHTURE §3.9).
4. **Đọc dữ liệu tính sẵn**: dự báo lấy từ bảng dự báo theo giờ ([backend_design §8](backend_design.md#8-dự-báo-bằng-model-đã-train-sẵn)), không chạy inference khi được hỏi, để phản hồi nhanh. Giới hạn thời gian chờ của Xiaozhi cho một lệnh gọi hàm chưa rõ.
5. **Response gọn**: số đã làm tròn, nhãn tiếng Việt, thời gian ISO 8601 múi giờ `+07:00`, có `summary_vi`.
6. **Nhận diện trạm**: `{ref}` nhận mã trạm (`ST001`, P15) hoặc tên. Khớp nhiều trạm → trả danh sách ứng viên để chatbot hỏi lại; không khớp trạm nào → lỗi có cấu trúc. Không nêu trạm → dùng trạm mặc định cấu hình trong backend. Không suy ra vị trí người dùng.
7. **Lỗi có cấu trúc**: `{"ok": false, "code": "...", "message_vi": "..."}`, ví dụ `STATION_NOT_FOUND`, `STATION_AMBIGUOUS`, `DATA_STALE`, `FORECAST_UNAVAILABLE`, `BACKEND_UNAVAILABLE` (bridge tự tạo khi không gọi được backend).
8. **Mốc dự báo:** đủ 24 mốc 3–72 giờ được công khai (P6); mốc độ tin cậy thấp luôn kèm nhãn, bridge đọc là "xu hướng", không đọc như con số chắc chắn.
9. **Không nêu trạm** (X5): bridge gọi với `ref = default` (dùng `default_station_id`); backend trả `DEFAULT_STATION_NOT_SET` thì bridge đọc danh sách trạm và hỏi lại.

---

## 6. Bảo mật và vận hành

| Mục | Thiết kế |
|---|---|
| Token Xiaozhi (`MCP_ENDPOINT`) | Bí mật, đặt trong biến môi trường của `xiaozhi-bridge`, không commit vào repo. |
| Xác thực bridge → backend | Token riêng, quyền duy nhất `assistant:read`, gửi qua header `Authorization: Bearer`. |
| Phạm vi mạng | Bridge gọi `http://api:8000` trong mạng Docker. Reverse proxy **không** định tuyến `/api/v1/assistant` ra Internet. |
| Giới hạn tần suất | Giới hạn số lệnh gọi mỗi phút cho token trợ lý. |
| Nhật ký | Ghi tên hàm, tham số, thời gian xử lý, kết quả (thành công/mã lỗi). Không có và không lưu giọng nói người dùng. |
| Cô lập sự cố | Bridge chết hoặc Xiaozhi gián đoạn không ảnh hưởng ingest, web, cảnh báo. Backend chết thì hàm trả `BACKEND_UNAVAILABLE`, chatbot báo không lấy được dữ liệu. |
| Tài nguyên | Bridge là tiến trình Python nhỏ, không nạp pandas/xgboost/model. |

---

## 7. Tiêu chí nghiệm thu

- Hỏi tiếng Việt lấy đúng trạm, đơn vị, thời điểm; số liệu khớp API web cùng thời điểm.
- Dự báo khớp bảng dự báo đã lưu (cùng phiên bản model).
- Xử lý đúng: trạm không tồn tại, tên trạm trùng, dữ liệu cũ, chưa đủ dữ liệu để dự báo, backend không phản hồi.
- Hỏi thông tin quản trị (pin, cảnh báo, Gateway) → chatbot không có hàm để trả lời.
- Tắt bridge trong lúc hệ thống chạy → ingest và web không bị ảnh hưởng.

---

## 8. Còn mở

Q7 (mốc công khai) và X5 (trạm mặc định) đã chốt ngày 04/10/2026, xem điểm 8–9 ở mục 5 và [backend_design §21](backend_design.md#21-quyết-định-p1p14-và-điểm-còn-chờ).

| # | Câu hỏi | Ảnh hưởng |
|---|---|---|
| X6 | Giới hạn thời gian chờ và kích thước kết quả của Xiaozhi cho một lệnh gọi hàm | Cần thử thực tế khi code; thiết kế hiện đã giữ response nhỏ và nhanh |
