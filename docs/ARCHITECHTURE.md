# ARCHITECTURE.md

## Hệ thống IoT Quan trắc & Dự đoán Chất lượng Không khí (AQI)

### 1. Tổng quan

Hệ thống thu thập dữ liệu chất lượng không khí từ mạng cảm biến không dây LoRa, lưu trữ, xử lý và huấn luyện mô hình dự đoán chỉ số AQI (US EPA, tính từ PM2.5/PM10) ở các mốc từ 3h đến 72h. Dữ liệu được hiển thị trực quan trên giao diện web (bản đồ + biểu đồ). **Chatbot Xiaozhi** bổ sung kênh hỏi đáp bằng giọng nói tiếng Việt để tra cứu số liệu, dự báo và trạng thái thiết bị từ cùng backend.

**Trạng thái tích hợp Xiaozhi:** nội dung dưới đây là thiết kế đề xuất; kho mã hiện chưa có firmware Xiaozhi, dịch vụ hội thoại hoặc công cụ MCP cho AQI. Các chức năng này cần được triển khai và kiểm chứng theo mục 3.9 trước khi coi là tính năng đã hoạt động.

Phần cứng kế thừa nguyên trạng từ đồ án *"Hệ thống giám sát chất lượng không khí đô thị sử dụng mạng cảm biến không dây LoRa"* (Nguyễn Đức Thắm, 2026 — `docs/NguyenDucTham_DATN_v2_checked.pdf`): Sensor Node và Gateway dùng ESP32, truyền LoRa 433 MHz point-to-point, Gateway đẩy dữ liệu lên server qua HTTP. Kiến trúc phía server được thiết kế để nhận đúng luồng dữ liệu này mà không cần sửa firmware.

Mục tiêu thiết kế: **tối giản techstack**, dùng một cơ sở dữ liệu duy nhất phục vụ cả truy vấn realtime lẫn phân tích (analytic), tránh over-engineering không cần thiết cho quy mô đồ án tốt nghiệp.

---

### 2. Sơ đồ kiến trúc tổng quát

![Sơ đồ kiến trúc tổng quát](architecture.svg)

<details>
<summary>Bản ASCII (xem trong terminal)</summary>

```
┌───────────────────────────┐
│ Sensor Node × N (ESP32)   │  PMS7003 · CCS811 · AHT10 · OLED
│ pin 18650, deep-sleep     │  đo 1 lần / 30 phút
└─────────────┬─────────────┘
              │ LoRa 433 MHz (AS32-TTL-100), point-to-point
              │ gói nhị phân 18 byte, không có timestamp
┌─────────────▼─────────────┐
│ Gateway (ESP32), nguồn 5V │  nhận LoRa → giải mã → ring buffer
└─────────────┬─────────────┘
              │ WiFi · HTTP POST (JSON batch) + heartbeat
┌─────────────▼─────────────────────┐  REST + WS/SSE  ┌──────────────────────────┐
│ FastAPI                           │ ──────────────▶ │ React + Vite (SPA, TS)   │
│ ingest · dedup · AQI · cảnh báo   │                 │ ECharts · deck.gl +      │
│ REST · WebSocket/SSE · inference  │                 │ MapLibre · R3F           │
└──────┬──────────────┬──────────┬──┘                 └──────────────────────────┘
       │              │          │
┌──────▼───────┐ ┌────▼─────┐ ┌──▼──────────────────┐
│ TimescaleDB  │ │ MinIO    │ │ XGBoost             │
│ + PostGIS    │ │ model,   │ │ training (script)   │
│ (DB duy nhất)│ │ dataset  │ │ đọc DB → ghi MinIO  │
└──────────────┘ └──────────┘ └─────────────────────┘

┌──────────────────────────┐  WiFi · WSS/Opus  ┌──────────────────────────────┐
│ Xiaozhi (ESP32-S3)        │ ◀──────────────▶ │ Xiaozhi Server (Python)      │
│ microphone · loa · nút   │                  │ ASR → LLM + tools → TTS      │
└──────────────────────────┘                  └──────────────┬───────────────┘
                                                           │ MCP nội bộ
                                                           ▼
                                             FastAPI: AQI MCP adapter /mcp
                                             → dữ liệu DB / inference XGBoost
```

</details>

Mô hình mạng cảm biến: **Hub-Spoke** — nhiều Sensor Node gửi về một Gateway trong bán kính phủ sóng LoRa; nhiều Gateway có thể cùng nhận một gói tin (server chống trùng lặp). Xiaozhi là thiết bị tương tác riêng, kết nối WiFi tới dịch vụ hội thoại; dữ liệu AQI được lấy qua FastAPI (chi tiết mục 3.9).

---

### 3. Thành phần hệ thống

#### 3.1. Tầng cảm biến (Sensor Node)

**Phần cứng** (theo báo cáo, mục 3.2 và 4.2.1):

| Linh kiện | Thông số đo / vai trò | Giao tiếp |
|---|---|---|
| ESP32 DevKit V1 (30 chân) | Vi điều khiển | — |
| PMS7003 (Plantower) | PM1, PM2.5, PM10 (0–2000 µg/m³), tán xạ laser | UART2 (GPIO25/26) |
| CCS811 | eCO2 (400–8192 ppm), TVOC (0–1187 ppb) — cảm biến MOX, **eCO2 là giá trị ước lượng, không phải CO2 đo NDIR** | I2C 0x5A |
| AHT10 | Nhiệt độ (−40–85 °C), độ ẩm (0–100 %RH) | I2C 0x38 |
| OLED SSD1306 0.96" | Hiển thị khi người dùng nhấn nút | I2C 0x3C |
| AS32-TTL-100 (SX1278) | LoRa 433 MHz, 20 dBm, chế độ UART transparent | UART1 (GPIO16/17), MD0/MD1 |
| Pin 18650 Li-ion | Nguồn; đo mức pin qua phân áp vào GPIO15 (ADC) | — |

**Firmware:**
- Chu kỳ **deep-sleep 30 phút**; mỗi lần thức khoảng 33 giây (khởi tạo → chờ PMS7003 warm-up khoảng 30 giây → đọc cảm biến → gửi LoRa) rồi ngủ lại.
- Provisioning: khi chưa cấu hình (hoặc giữ nút BOOT 5 giây để factory reset), node phát WiFi AP `AirQuality-SN-Setup`, người dùng nhập Node ID qua captive portal `192.168.4.1`, lưu vào NVS. Ngoài lúc provisioning, Sensor Node **không dùng WiFi**.

**Gói tin LoRa (18 byte, struct C packed):**

| Trường | Kích thước | Ghi chú |
|---|---|---|
| `nodeId` | 1 B | 1–255, map sang `NODE_XXX` phía server |
| `pktType` | 1 B | dữ liệu / heartbeat / lỗi |
| `msgId` | 1 B | bộ đếm vòng 0–255, dùng cho dedup |
| `pm1`, `pm25`, `pm10` | 3 × 2 B | ×10 |
| `co2`, `tvoc` | 2 × 2 B | nguyên |
| `temp` | 2 B | có dấu, ×10 |
| `hum` | 2 B | ×10 |
| `battery` | 1 B | 0–100 % |

Giá trị sentinel `0xFFFF` (unsigned) / `0x7FFF` (signed) đánh dấu cảm biến lỗi → server lưu `NULL`. Gói tin **không chứa thời gian** vì node không đồng bộ được đồng hồ.

#### 3.2. Tầng trung chuyển (Gateway)

- **Phần cứng:** ESP32 DevKit V1 + AS32-TTL-100 (cùng cấu hình chân với Sensor Node) + OLED SSD1306, cấp nguồn 5V liên tục.
- **Firmware (superloop):** nhận gói LoRa từ UART → giải mã → tích lũy vào ring buffer → khi đủ số gói hoặc hết chu kỳ thời gian thì serialize thành JSON array và gửi **HTTP POST** lên server. Gateway gửi heartbeat định kỳ và tự đăng ký với server ở lần kết nối đầu (self-provisioning).
- **Timestamp:** vì gói LoRa không có thời gian và Gateway gửi theo batch, mỗi bản ghi trong batch cần mang thời điểm Gateway nhận gói (đồng hồ đồng bộ NTP). Nếu thiếu, server dùng thời điểm nhận request (sai lệch tối đa bằng chu kỳ flush của ring buffer). *Cần kiểm tra firmware Gateway hiện có đã gửi trường này chưa.*
- **Tầm phủ:** thực đo **800 m** ở không gian thoáng (line-of-sight); trong khu dân cư có vật cản sẽ thấp hơn.
- Không dùng MQTT broker cho telemetry: Gateway gửi dữ liệu cảm biến lên server qua HTTP theo firmware hiện có. Kênh hội thoại Xiaozhi dùng WebSocket (mục 3.9), nên cũng không cần bổ sung Mosquitto.

#### 3.3. Tầng tiếp nhận dữ liệu (Ingest — trong FastAPI)

- **Endpoint:** `POST /api/telemetry` (batch từ Gateway, kèm `gateway_id`), `POST /api/heartbeat`.
- **Pipeline xử lý mỗi batch:**
  1. Validate payload, chuyển sentinel thành `NULL`, chia lại hệ số ×10.
  2. **Dedup** theo `(nodeId, msgId)` trong cửa sổ ngắn (vd. 10 phút) — xử lý trường hợp nhiều Gateway nhận cùng một gói. Với chu kỳ 30 phút, `msgId` 1 byte chỉ quay vòng sau khoảng 128 giờ nên cửa sổ ngắn là an toàn.
  3. Transaction: cập nhật `last_seen`, `battery_level`, `lora_rssi` của Gateway/Node và ghi bản ghi vào `measurements`.
  4. Tính AQI (US EPA, max của sub-index PM2.5 và PM10).
  5. Kiểm tra ngưỡng cảnh báo **ngoài transaction** (lỗi cảnh báo không làm mất dữ liệu đo), cooldown 15 phút cho cùng node + cùng thông số.
  6. Đẩy bản ghi mới tới frontend qua WebSocket/SSE.
- **Phát hiện offline:** job định kỳ 5 phút; Sensor Node offline sau **40 phút** không có dữ liệu (lớn hơn chu kỳ đo 30 phút), Gateway offline sau **5 phút** không có heartbeat.

#### 3.4. Tầng lưu trữ (Storage Layer)

- **TimescaleDB + PostGIS** (một instance PostgreSQL) là database duy nhất của hệ thống:
  - `measurements` — hypertable, khóa `(time, node_id)`: `pm1, pm2_5, pm10, eco2, tvoc, temperature, humidity, aqi`.
  - `hourly_measurements` — Continuous Aggregate trung bình theo giờ; vừa phục vụ biểu đồ lịch sử, vừa là **đầu vào inference** của mô hình (cùng tần suất giờ với dataset huấn luyện).
  - `gateways`, `sensor_nodes` (cột `geom geometry(Point, 4326)` cho truy vấn trạm gần nhất bằng PostGIS), `alerts`, `alert_configs`, `users`, `audit_logs`.
  - Retention: dữ liệu thô giữ có thời hạn (báo cáo dùng 3 tháng); dữ liệu tổng hợp theo giờ giữ lâu dài làm dữ liệu huấn luyện.
- **MinIO:** lưu trữ file nhị phân — dataset CSV (~41.000 dòng theo giờ, 01/2022–09/2026), model artifact đã huấn luyện, log/checkpoint nếu cần.

> Lý do bỏ ClickHouse: một database (TimescaleDB) đáp ứng được cả truy vấn realtime và truy vấn tổng hợp/phân tích ở quy mô dữ liệu của đồ án, giảm độ phức tạp vận hành.

#### 3.5. Tầng xử lý & Dự đoán (Processing & ML Layer)

- **Mô hình:** XGBoost (pipeline tại `ml_xgb/`).
- **Biến mục tiêu:** AQI tại `t+h`, với `h` = 3, 6, …, 72 giờ (bước 3h). Giao diện nhấn mạnh các mốc 12h/24h/48h/72h.
- **Dữ liệu huấn luyện:** `data/dataset.csv` — các cột `AQI, pm10, pm2_5, Humidity, Temperature` theo giờ (file theo năm, từ 07/2025 là Open-Meteo); feature gồm lag 1–72h và thống kê trượt 3–72h.
- **Ánh xạ cảm biến → feature:**

  | Feature | Nguồn từ phần cứng |
  |---|---|
  | `pm2_5`, `pm10` | PMS7003 |
  | `Temperature`, `Humidity` | AHT10 |
  | `AQI` | tính trên server từ PM2.5/PM10 |
  | — | eCO2, TVOC, PM1 **không có trong dataset** → chỉ dùng để hiển thị và cảnh báo, không làm feature |

  Dữ liệu node (30 phút/mẫu) được lấy trung bình theo giờ từ `hourly_measurements` trước khi đưa vào mô hình.
- **Điều kiện inference:** feature lag/rolling cần lịch sử liên tục tới 72 giờ của node. Node dùng cho dự đoán phải được cấp nguồn ngoài (pin hiện chỉ trụ khoảng 20,5 giờ); giờ thiếu dữ liệu được xử lý theo `NAN_POLICY` của pipeline.
- Không dùng Spark/Kafka/MLflow — huấn luyện chạy bằng script Python, model lưu trong MinIO; FastAPI load model để inference.

> Lý do bỏ Spark & MLflow: khối lượng dữ liệu (~41k dòng) không cần xử lý phân tán; việc quản lý vòng đời mô hình ở mức đồ án có thể làm thủ công/đơn giản hóa mà không cần MLflow.

#### 3.6. Tầng Backend / API

- **FastAPI:** cung cấp REST API và kênh WebSocket/SSE cho:
  - Tiếp nhận telemetry/heartbeat từ Gateway (mục 3.3)
  - Dữ liệu cảm biến realtime & lịch sử (query từ TimescaleDB), trạm gần nhất (PostGIS)
  - Kết quả dự đoán (từ model XGBoost)
  - Quản lý Gateway/Sensor Node, cấu hình ngưỡng, cảnh báo
  - **AQI MCP adapter** dự kiến mount tại `/mcp` trên mạng nội bộ: cung cấp các công cụ đọc dữ liệu cho Xiaozhi Server, dùng chung lớp nghiệp vụ với REST API (mục 3.9)
- Giao tiếp với TimescaleDB và MinIO.

#### 3.7. Tầng giao diện người dùng (Frontend)

- **React + Vite + TypeScript (SPA)** — chỉ đóng vai trò tầng giao diện; toàn bộ logic nghiệp vụ và truy vấn dữ liệu nằm ở FastAPI. Frontend chỉ gọi REST API và nhận WebSocket/SSE, không truy cập trực tiếp database.
- **Routing & tải trang:** React Router cho các trang (tổng quan, lịch sử, bản đồ, xếp hạng, quản trị); tách bundle theo route bằng `React.lazy` + `Suspense` để các thư viện nặng (deck.gl, Three.js) chỉ tải khi vào trang cần dùng.
- **ECharts:** biểu đồ xu hướng AQI/PM2.5 và các thông số theo thời gian, biểu đồ dự đoán AQI (nổi bật mốc 12h/24h/48h/72h)
- **deck.gl + MapLibre GL:** bản đồ 3D hiển thị vị trí trạm, cột 3D có chiều cao/màu theo AQI (thay thế Leaflet)
- **React Three Fiber + drei:** hiệu ứng 3D trang chủ (mô hình trạm cảm biến, hiệu ứng hạt bụi mịn có mật độ theo giá trị PM2.5 hiện tại)
- **Realtime:** kết nối WebSocket/SSE tới FastAPI để nhận dữ liệu mới. Mỗi node chỉ có điểm dữ liệu mới khoảng 30 phút một lần; giao diện hiển thị thời điểm đo gần nhất và trạng thái online/offline, mức pin của thiết bị.
- **Hiệu năng 3D:** lazy load + `Suspense`, giới hạn số hạt, fallback 2D cho thiết bị yếu và khi người dùng bật `prefers-reduced-motion`

#### 3.8. Hạ tầng triển khai

- **Docker Compose:** đóng gói và chạy toàn bộ các service phía server (TimescaleDB + PostGIS, MinIO, FastAPI, Nginx, service huấn luyện), dự kiến bổ sung **Xiaozhi Server** dạng cài đặt tối giản chỉ chạy Python server. AQI MCP adapter nằm trong FastAPI; nhánh chatbot dùng lại dữ liệu của backend.
- **Kết nối Gateway → server:** endpoint ingest của FastAPI phải truy cập được từ mạng WiFi của Gateway — IP LAN khi demo tại chỗ, hoặc domain công khai (HTTPS qua reverse proxy) khi triển khai trên VPS. Địa chỉ server được cấu hình trong firmware Gateway.
- **Frontend React** được build bằng Vite thành file tĩnh, phục vụ bởi container **Nginx**. Nginx đồng thời làm reverse proxy: `/api` và kênh WebSocket/SSE chuyển tới FastAPI, còn các route SPA khác fallback về `index.html`. Nhờ frontend và API cùng origin, không cần cấu hình CORS; địa chỉ API (nếu khác origin) đặt qua biến build-time `VITE_API_URL`.
- **Kênh Xiaozhi:** dự kiến cấu hình Nginx chuyển `/xiaozhi/v1/` tới WebSocket server và `/xiaozhi/ota/` tới HTTP endpoint cấu hình/OTA của Xiaozhi Server; giữ nguyên đường dẫn upstream, hỗ trợ WebSocket Upgrade và timeout cho phiên thoại. Thiết bị được cấu hình địa chỉ server riêng. `/mcp` chỉ mở trong mạng Docker cho dịch vụ hội thoại.

#### 3.9. Chatbot Xiaozhi — trợ lý giọng nói về chất lượng không khí

**Xiaozhi là gì?** `xiaozhi-esp32` là dự án chatbot giọng nói mã nguồn mở. Thiết bị ESP32 đảm nhiệm thu/phát âm thanh và tương tác với người dùng; dịch vụ hội thoại kết nối mô hình ngôn ngữ và các công cụ qua **MCP (Model Context Protocol)**. Tham khảo [dự án firmware Xiaozhi](https://github.com/78/xiaozhi-esp32). Trong đồ án, vai trò được đề xuất là biến dữ liệu quan trắc thành câu trả lời dễ hiểu, có thể hỏi trực tiếp bằng tiếng Việt.

**Tác dụng trong hệ thống:**

| Nhu cầu | Ví dụ câu hỏi | Dữ liệu/cách xử lý đề xuất |
|---|---|---|
| Tra cứu số liệu gần nhất | “AQI ở trạm NODE_001 hiện tại là bao nhiêu?” | Đọc AQI, PM2.5, PM10, thời điểm đo và trạng thái trạm từ FastAPI |
| Tra cứu dự báo | “Trạm này sau 24 giờ có ô nhiễm hơn không?” | Gọi inference XGBoost, đối chiếu với số đo gần nhất và đọc rõ mốc dự báo |
| Xem xu hướng và so sánh | “24 giờ qua bụi mịn tăng hay giảm?” | Lấy dữ liệu tổng hợp theo giờ; backend tính thống kê, chatbot diễn đạt kết quả |
| Giải thích thông số | “PM2.5, AQI và eCO2 có nghĩa là gì?” | Dùng nội dung giải thích đã kiểm duyệt; nêu đúng eCO2 là giá trị ước lượng |
| Hỗ trợ quản trị | “Trạm nào đang offline hoặc sắp hết pin?” | Đọc trạng thái node/gateway và cảnh báo theo quyền tài khoản/thiết bị |

Lợi ích chính là giảm thao tác tìm biểu đồ, hỗ trợ người dùng nghe số liệu và tạo kịch bản demo tương tác cho đồ án. Các chức năng AQI ở bảng trên là **công cụ riêng cần xây dựng**, không tự xuất hiện khi cài Xiaozhi. LLM hiểu câu hỏi, chọn công cụ và diễn đạt; FastAPI tính AQI/thống kê, XGBoost sinh dự báo.

**Kiến trúc tích hợp được chọn:**

1. **Thiết bị thoại riêng:** ESP32-S3 với board được firmware Xiaozhi hỗ trợ, microphone, loa và mạch âm thanh phù hợp; màn hình tùy chọn, cấp nguồn ngoài khi demo. Sensor Node và Gateway giữ nguyên phần cứng/firmware kế thừa.
2. **Thiết bị ↔ Xiaozhi Server:** chọn WiFi + WebSocket/WSS; âm thanh truyền bằng Opus, trạng thái hội thoại bằng JSON theo [giao thức WebSocket Xiaozhi](https://github.com/78/xiaozhi-esp32/blob/main/docs/websocket.md). Kênh này độc lập với WebSocket/SSE cập nhật dashboard.
3. **Dịch vụ hội thoại:** dùng bản Python tự triển khai của [xinnan-tech/xiaozhi-esp32-server](https://github.com/xinnan-tech/xiaozhi-esp32-server), theo [phương án chỉ chạy Server](https://github.com/xinnan-tech/xiaozhi-esp32-server/blob/main/docs/Deployment.md). Pipeline: ASR (giọng nói → văn bản) → LLM có khả năng gọi công cụ → TTS (văn bản → giọng nói). Chọn ASR/TTS hỗ trợ tiếng Việt và kiểm tra với giọng nói thực tế; cấu hình provider qua file, tránh thêm tầng quản trị và database riêng ở giai đoạn đồ án.
4. **Xiaozhi Server ↔ FastAPI:** xây AQI MCP adapter bằng Python MCP SDK, mount vào FastAPI tại `/mcp`, transport **Streamable HTTP**. Đây là MCP phía server để truy vấn dữ liệu AQI. Xiaozhi Server hỗ trợ cấu hình MCP qua `data/.mcp_server_settings.json` ([MCP manager](https://github.com/xinnan-tech/xiaozhi-esp32-server/blob/main/main/xiaozhi-server/core/providers/tools/server_mcp/mcp_manager.py)); client có transport `streamable-http` và header xác thực ([MCP client](https://github.com/xinnan-tech/xiaozhi-esp32-server/blob/main/main/xiaozhi-server/core/providers/tools/server_mcp/mcp_client.py)). Adapter dùng chung logic truy vấn và inference với REST API; cần kiểm tra tương thích với phiên bản server được chốt khi triển khai.

**Hợp đồng công cụ MCP dự kiến:**

| Công cụ | Tham số chính | Kết quả |
|---|---|---|
| `get_current_air_quality` | `node_id` | AQI, mức phân loại do backend tính, PM2.5/PM10, thời điểm đo, trạng thái dữ liệu |
| `get_air_quality_history` | `node_id`, `start`, `end` | Chuỗi theo giờ và thống kê do backend tính; giới hạn tối đa 72 giờ mỗi lần gọi |
| `get_air_quality_forecast` | `node_id`, `horizon_hours` (3, 6, …, 72) | AQI dự báo, thời điểm dữ liệu đầu vào, thời điểm đích và phiên bản mô hình |
| `get_station_status` | `node_id` hoặc bộ lọc trạng thái | Thời điểm thấy gần nhất, pin, online/offline và cảnh báo còn hiệu lực trong phạm vi được cấp quyền |

Nếu người dùng chưa nêu trạm, dùng trạm mặc định đã cấu hình hoặc hỏi lại; không suy ra vị trí người dùng từ câu nói. Thời gian nhập/trả về dùng ISO 8601 có múi giờ; khi đọc “ngày mai”, server quy đổi theo `Asia/Bangkok` và yêu cầu giờ cụ thể nếu cần xác định mốc dự báo.

**Độ tin cậy và phạm vi:** mọi câu trả lời có số liệu phải dựa vào kết quả công cụ và nêu trạm, thời điểm đo hoặc thời điểm dự báo. Dữ liệu “hiện tại” là mẫu gần nhất với chu kỳ đo 30 phút; mẫu quá 40 phút được đánh dấu cũ/offline. Nếu thiếu lịch sử cho inference (mục 3.5), công cụ trả lỗi có cấu trúc; chatbot thông báo chưa đủ dữ liệu. Xác thực thiết bị thoại, dùng token giới hạn quyền cho MCP, kiểm tra tham số/phạm vi trạm tại backend và lưu dấu vết lời gọi trong `audit_logs`. Bản đầu chỉ cung cấp công cụ đọc dữ liệu; cảnh báo tự động vẫn do pipeline ingest xử lý. Phát cảnh báo chủ động qua loa là hướng mở rộng, cần bổ sung cơ chế gửi sự kiện và quản lý phiên thiết bị.

**Tiêu chí nghiệm thu:** hỏi tiếng Việt lấy được số liệu đúng trạm/đơn vị/thời điểm; dự báo khớp kết quả REST API cùng đầu vào; xử lý đúng trạm không tồn tại, dữ liệu cũ, thiếu lịch sử và lỗi provider; chatbot mất kết nối không ảnh hưởng ingest, dashboard hoặc cảnh báo. Hiện tại chưa thực hiện các kiểm thử tích hợp này.

---

### 4. Luồng dữ liệu (Data Flow)

1. Sensor Node thức dậy mỗi 30 phút → đọc PMS7003, CCS811, AHT10, mức pin → đóng gói 18 byte → phát LoRa 433 MHz → ngủ lại
2. Gateway nhận gói LoRa → giải mã, gán thời điểm nhận → lưu ring buffer → gửi HTTP POST (JSON batch) lên FastAPI; heartbeat định kỳ
3. FastAPI ingest: validate → dedup `(nodeId, msgId)` → ghi TimescaleDB → tính AQI → kiểm tra ngưỡng cảnh báo → đẩy realtime qua WebSocket/SSE
4. TimescaleDB tự động cập nhật `hourly_measurements` (trung bình theo giờ)
5. Định kỳ (hoặc theo yêu cầu), pipeline huấn luyện đọc dataset gốc (MinIO) + dữ liệu lịch sử theo giờ (TimescaleDB) → huấn luyện XGBoost → lưu model vào MinIO
6. FastAPI load model từ MinIO → lấy 72 giờ gần nhất của node từ `hourly_measurements` → sinh dự đoán AQI 3h–72h → trả về frontend
7. Frontend React (SPA) gọi REST API lấy dữ liệu ban đầu, nhận cập nhật qua WebSocket/SSE, hiển thị dữ liệu realtime (ECharts), bản đồ 3D (deck.gl + MapLibre), hiệu ứng 3D (React Three Fiber) và kết quả dự đoán
8. **Nhánh hội thoại dự kiến:** người dùng nói → thiết bị Xiaozhi gửi Opus qua WSS → Xiaozhi Server nhận dạng tiếng Việt → LLM gọi công cụ MCP → FastAPI truy vấn TimescaleDB hoặc inference XGBoost → trả dữ liệu có thời điểm → LLM diễn đạt → TTS gửi âm thanh về loa. Đây là luồng truy vấn theo yêu cầu, chạy song song với luồng thu thập dữ liệu cảm biến.

---

### 5. Techstack tổng hợp

| Thành phần          | Công nghệ                          |
|---------------------|-------------------------------------|
| Sensor Node         | ESP32 DevKit V1, PMS7003, CCS811, AHT10, OLED SSD1306, pin 18650 |
| Truyền thông không dây | LoRa 433 MHz point-to-point (AS32-TTL-100 / SX1278), gói nhị phân 18 byte |
| Gateway             | ESP32 DevKit V1 + AS32-TTL-100, WiFi, HTTP POST (JSON batch) |
| Database            | TimescaleDB + PostGIS (duy nhất)    |
| Object storage      | MinIO                               |
| Machine Learning    | XGBoost                             |
| Backend API         | FastAPI                             |
| Frontend            | React + Vite, TypeScript, React Router, ECharts |
| Web server          | Nginx (phục vụ file tĩnh + reverse proxy tới FastAPI) |
| Bản đồ & 3D         | deck.gl + MapLibre GL, React Three Fiber + drei |
| Thiết bị chatbot (đề xuất) | ESP32-S3, firmware xiaozhi-esp32, microphone + loa, WiFi, WSS/Opus |
| Dịch vụ hội thoại (đề xuất) | xiaozhi-esp32-server (Python, chỉ chạy Server), ASR + LLM gọi công cụ + TTS tiếng Việt |
| Kết nối chatbot → dữ liệu (đề xuất) | Python MCP SDK, AQI MCP adapter trong FastAPI, Streamable HTTP nội bộ |
| Triển khai          | Docker Compose                      |

---

### 6. Các quyết định kiến trúc chính (Architecture Decision Log)

| Quyết định | Lý do |
|---|---|
| Giữ nguyên phần cứng và firmware của báo cáo | Hệ thống phần cứng đã chạy ổn định (ESP32 + LoRa); phía server thiết kế quanh định dạng dữ liệu Gateway đang gửi để không phải sửa firmware |
| LoRa point-to-point thay vì LoRaWAN | Theo báo cáo: đơn giản hóa kiến trúc, giảm chi phí; chỉ cần truyền trong phạm vi một khu vực |
| Gateway gửi HTTP trực tiếp tới FastAPI, không dùng MQTT/Mosquitto | Telemetry đã dùng HTTP POST batch; Xiaozhi chọn WebSocket cho hội thoại, nên không cần broker; ring buffer trên Gateway đảm nhiệm việc đệm khi mất kết nối |
| Bỏ Kafka | Không cần xử lý luồng phân tán khối lượng lớn; lưu lượng chỉ vài gói/giờ mỗi node |
| Dùng TimescaleDB thay vì TimescaleDB + ClickHouse | Giảm số lượng database cần vận hành; TimescaleDB đáp ứng đủ cho cả realtime và analytic ở quy mô đồ án |
| Thêm PostGIS vào cùng instance | Truy vấn trạm gần nhất theo vị trí người dùng, không cần database thứ hai |
| Backend dùng FastAPI thay vì Node.js/Express như báo cáo | Cùng ngôn ngữ Python với pipeline ML, load và chạy model XGBoost trực tiếp trong backend |
| Bỏ Spark | Khối lượng dữ liệu nhỏ (~41k dòng), xử lý bằng pandas/script Python là đủ |
| Bỏ MLflow | Quy mô đồ án không cần hệ thống quản lý vòng đời mô hình phức tạp |
| Giữ MinIO | Cần nơi lưu dataset gốc và model artifact tách biệt khỏi database |
| Dự đoán AQI các mốc 3h–72h, nổi bật 12h/24h/48h/72h | Phù hợp với mục tiêu cảnh báo sớm chất lượng không khí trong 1–3 ngày tới; AQI là chỉ số người dùng đọc trực tiếp |
| Chỉ dùng PM2.5, PM10, nhiệt độ, độ ẩm làm feature | Đây là phần giao giữa dataset huấn luyện và thông số phần cứng đo được |
| Frontend dùng React SPA (Vite) thay vì Next.js | Giao diện là dashboard tương tác, nội dung chủ yếu là dữ liệu realtime render phía client nên SSR/SEO không mang lại nhiều lợi ích; SPA build ra file tĩnh, phục vụ bằng Nginx, bớt một container Node.js và tránh có hai tầng server song song; đồng nhất với hướng React + Vite của báo cáo |
| Thay Leaflet bằng deck.gl + MapLibre | Hỗ trợ trực quan hóa 3D (cột AQI theo chiều cao), tránh dùng hai thư viện bản đồ |
| Thêm React Three Fiber | Tạo hiệu ứng 3D trực quan cho trang chủ, gắn với dữ liệu PM2.5 thực tế |
| Bổ sung Xiaozhi như thiết bị thoại riêng (đề xuất) | Hỏi đáp AQI bằng giọng nói mà vẫn giữ nguyên Sensor Node/Gateway kế thừa |
| Tự triển khai Xiaozhi Python Server dạng tối giản (đề xuất) | Chủ động cấu hình tiếng Việt và công cụ AQI; chỉ thêm dịch vụ hội thoại, dùng chung backend dữ liệu |
| Kết nối công cụ AQI qua MCP trong FastAPI (đề xuất) | Tái sử dụng truy vấn/inference và quyền truy cập; LLM diễn đạt số liệu do backend trả về |

---

### 7. Giới hạn & hướng mở rộng

- **Pin:** prototype dùng board DevKit nên dòng deep-sleep khoảng 26 mA (chip USB-UART, LDO, LED); pin 1500 mAh chỉ trụ khoảng **20,5 giờ**. Node phục vụ dự đoán cần nguồn ngoài; hướng cải thiện là dùng module ESP32 trần và pin dung lượng lớn hơn.
- **Tầm LoRa:** thực đo 800 m line-of-sight, thấp hơn nhiều so với công bố 3 km; vị trí đặt Gateway quyết định vùng phủ.
- **Độ chính xác cảm biến:** cảm biến giá rẻ chưa được hiệu chuẩn. PMS7003 có xu hướng đo cao khi độ ẩm cao (Hà Nội thường 70–97 %RH); eCO2 của CCS811 là giá trị ước lượng từ cảm biến MOX, không thay thế được CO2 đo NDIR.
- **Lệch miền dữ liệu (domain shift):** mô hình học trên dữ liệu quan trắc/mô hình hóa (file năm, Open-Meteo), còn inference chạy trên dữ liệu PMS7003 tại điểm đặt node. Cần đánh giá sai số trên dữ liệu thực tế trước khi tin vào dự đoán; có thể bổ sung bước hiệu chỉnh theo độ ẩm hoặc hiệu chuẩn bias bằng cách đặt node cạnh trạm chuẩn.
- **Thời gian:** Sensor Node không có đồng hồ thực; độ chính xác timestamp phụ thuộc vào Gateway (NTP) và chu kỳ flush ring buffer.
- **Mở rộng truyền thông:** tích hợp LoRaWAN (ChirpStack/The Things Network) để dùng hạ tầng sẵn có và điều chỉnh chu kỳ đo từ xa qua downlink.
- **Mở rộng quy mô:** nếu số lượng Gateway/trạm tăng lớn, có thể đưa MQTT broker hoặc Kafka vào giữa Gateway và backend ở giai đoạn sau.
- **Xiaozhi:** chất lượng nhận dạng/phát âm tiếng Việt và độ trễ phụ thuộc microphone, mạng và provider ASR/LLM/TTS; cần đo khi demo. Tự triển khai server vẫn cần Internet nếu dùng provider bên ngoài và có thể phát sinh phí API. Mặc định đề xuất không lưu âm thanh hội thoại lâu dài; dữ liệu gửi provider cần được xác định khi chọn cấu hình triển khai.
- **Mở rộng chatbot:** thêm tra cứu trạm gần nhất bằng PostGIS khi có vị trí được cung cấp rõ ràng; tích hợp giao diện chat trên web qua adapter phiên riêng; bổ sung đọc cảnh báo chủ động qua loa. Các mục này chưa thuộc phạm vi bản tích hợp đầu tiên.
