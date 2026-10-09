# 01 — Đánh giá kiến trúc hiện tại và lựa chọn FastAPI

**Trạng thái:** đã chốt Q1–Q4 (03/10/2026). Các câu hỏi còn mở ở mục 8.2 được xử lý ở các phần sau.
**Cập nhật:** 03/10/2026
**Phạm vi:** đánh giá hiện trạng và chọn hướng đi. Database, API, Admin, visualization được thiết kế chi tiết ở các phần sau (xem [README](README.md)).

---

## 1. Nguồn đã đọc

| Nguồn | Nội dung dùng cho thiết kế |
|---|---|
| [`PLAN.md`](../../PLAN.md) | 14 yêu cầu của bước thiết kế |
| [`docs/ARCHITECHTURE.md`](../ARCHITECHTURE.md) | Kiến trúc đang dự kiến |
| [`docs/FORESCATING.md`](../FORESCATING.md) | Kết quả và giới hạn thực tế của mô hình |
| [`docs/Base.pdf`](../Base.pdf) (96 trang) | Chương 2 (use case), 4.2.4–4.2.5 (backend, ERD), 4.3.3 (giao diện), 4.5 (triển khai, vận hành), 5.3 (pipeline telemetry), 6 (hạn chế) |
| `base_code.zip` → `datn-main/firmware/` | Mã nguồn firmware của Base: `gateway`, `gateway-30pin`, `sensor-node`, `sensor-node-30pin`, `sensor-node-30pin-deepsleep` |
| `base_code.zip` → `datn-main/docs/firmware/` | Tài liệu giao thức LoRa, Gateway, Sensor Node của Base |
| `base_code.zip` → `datn-main/backend/` | Chỉ đọc phần nhận telemetry/provisioning để biết firmware mong đợi server trả gì. **Không dùng lại thiết kế.** |
| [`ml/ml_xgb/src/`](../../ml/ml_xgb/src/) | `config`, `data_loading`, `preprocessing`, `feature_engineering`, `targets`, `split`, `train`, `predict`, `aqi` |
| [`ml/ml_xgb/models/xgb_AQI_h3.meta.json`](../../ml/ml_xgb/models/) | Metadata thật của model đã train |
| [`ml/ml_rf/rf/predict.py`](../../ml/ml_rf/rf/predict.py) | Cách RF tái sử dụng phần inference của XGBoost |
| [`ml/data/`](../../ml/data/) | Định dạng `dataset.csv` và các file nguồn |

Trong repo hiện tại, `backend/`, `frontend/`, `firmware/`, `docker/`, `infra/` đang **trống**.

---

## 2. Hiện trạng đã kiểm chứng

### 2.1. Phần cứng (Base.pdf)

- **Sensor Node:** ESP32 + PMS7003 (PM1/2.5/10) + CCS811 (eCO2, TVOC) + AHT10 (nhiệt độ, độ ẩm). Pin 1500 mAh trụ **20,5 giờ** ở chế độ deep-sleep 30 phút.
- **Gói LoRa:** 18 byte, **không có thời gian**, `msgId` 1 byte (0–255).
- **Triển khai Base:** DigitalOcean 1 vCPU / 1 GB RAM / 25 GB, 4 container (`timescaledb-ha:pg15`, backend Node.js, Nginx, Certbot).
- **Dữ liệu thật trong Base:** chỉ một node (`NODE_076`); các trạm khác là dữ liệu mô phỏng (mục 4.3.3).

### 2.2. Hợp đồng firmware thực tế (đọc từ mã nguồn)

Firmware **giữ nguyên** (quyết định Q1), nên backend phải chấp nhận đúng những gì firmware gửi. Mã nguồn khác với cả Base.pdf lẫn `docs/firmware/` của Base ở nhiều điểm (mục 3.4), nên bảng dưới đây lấy **code làm chuẩn**.

**Các endpoint firmware gọi:**

| Firmware | Request | Firmware coi là thành công khi |
|---|---|---|
| Gateway, lúc provisioning | `POST {SERVER_BASE_URL}/api/v1/provision/gateway` body `{provision_key, name, location_desc}` | HTTP **201**, đọc `data.id` (vd. `GW_001`) |
| Sensor Node, lúc provisioning | `GET /api/v1/provision/gateways?provision_key=…` | HTTP **200**, đọc `data[]` để hiện danh sách Gateway |
| Sensor Node, lúc provisioning | `POST /api/v1/provision/node` body `{provision_key, name, gateway_id, lat?, lng?}` | HTTP **201**, đọc `data.id` và `data.node_numeric_id` (kiểu `uint8`, 1–255) |
| Gateway, khi xả buffer | `POST /api/v1/telemetry` | HTTP **200** (mã khác, kể cả 201/204, bị coi là lỗi) |
| Gateway, mỗi 5 phút | `POST /api/v1/telemetry/heartbeat` body `{gateway_id, secret}` | HTTP 200 |

**Body telemetry (`gateway-30pin/src/net/http_client.cpp`):**

```json
{
  "gateway_id": "GW_001",
  "secret": "super-secret-key",
  "data": [
    {
      "node_id": "NODE_076",
      "pm25": 70.0, "pm10": 60.0,
      "co2": 800, "tvoc": 120,
      "temperature": 32.5, "humidity": 70.0,
      "battery": 92, "rssi": 0
    }
  ]
}
```

**Các sự thật ảnh hưởng thiết kế:**

| # | Sự thật trong code | Nguồn | Hệ quả cho backend |
|---|---|---|---|
| F1 | `gateway-30pin` **không gửi `msg_id`**; bản `gateway` (không phải 30pin) có gửi | diff `http_client.cpp` hai bản | Không thể chỉ dựa vào `(node, msgId)` để chống trùng. `msg_id` là trường tùy chọn. |
| F2 | Không có thời gian đo trong JSON; Gateway có `receivedAt` (millis) nhưng không gửi | `packet_buffer.h`, `http_client.cpp` | Thời điểm đo = thời điểm server nhận, trừ ước lượng. Sai lệch bình thường ≤ 30 giây (chu kỳ xả buffer). |
| F3 | Buffer Gateway 10 gói; mất WiFi thì giữ gói; **buffer đầy thì bỏ gói mới** | `packet_buffer.cpp`, `main.cpp` | Sau sự cố mạng, một batch có thể chứa nhiều bản ghi cũ của cùng node, tất cả đến cùng lúc. Gán chung thời điểm nhận sẽ dồn nhiều mẫu vào một giờ. |
| F4 | Gửi lỗi (mã ≠ 200) → thử lại 3 lần rồi **đẩy lại vào buffer** | `http_client.cpp`, `main.cpp` | Server phải **luôn trả 200** khi đã nhận batch hợp lệ về cú pháp, kể cả khi bỏ một số bản ghi. Nếu server đã lưu nhưng phản hồi chậm/lỗi, Gateway gửi lại → phải chống trùng theo nội dung. |
| F5 | PM2.5, PM10, nhiệt độ, độ ẩm lỗi → gửi `null`. **CO2, TVOC lỗi vẫn gửi số**: `0` khi CCS811 chưa có dữ liệu (CO2 < 400 hoặc rác), `65535` khi sentinel | `http_client.cpp`, `ccs811.cpp` | Chuẩn hóa ở biên: `co2 < 400` hoặc `65535` → `NULL`, kéo theo TVOC `NULL`. |
| F6 | PM1 có trong gói LoRa nhưng **không được gửi lên** | `http_client.cpp` | Không có PM1 trong DB (không ảnh hưởng ML). |
| F7 | `rssi` luôn bằng `0` (module AS32 không cung cấp RSSI) | `lora_receiver.cpp` | Không hiển thị RSSI như số đo thật; lưu `NULL`. |
| F8 | `pktType` không được gửi lên. Node chạy liên tục gửi **gói heartbeat toàn số 0** (chỉ có `battery`) sau 10 phút không có dữ liệu; Gateway chuyển tiếp như bản ghi bình thường | `sensor-node-30pin/src/tasks/lora_task.cpp` | Bản ghi có PM2.5 = PM10 = nhiệt độ = độ ẩm = CO2 = TVOC = 0 là **heartbeat của node**: cập nhật `last_seen`, pin; **không lưu thành số đo**. Gói `PKT_TYPE_ERROR` không node nào gửi. |
| F9 | `node_id` là chuỗi `NODE_%03d` tạo từ `nodeId` 1 byte | `http_client.cpp` | Mã số node phải trong 1–255, duy nhất; server cấp khi provisioning. |
| F10 | Xác thực telemetry bằng **một `secret` chung** cho mọi Gateway, nằm trong body | `config.h`, `http_client.cpp` | Không có khóa riêng từng Gateway nếu không sửa firmware. Biện pháp bù ở Phần 05. |
| F11 | Gateway và Node dùng `WiFiClientSecure` + `setInsecure()` | `http_client.cpp`, `captive_portal.cpp` | Server **phải có HTTPS** (chấp nhận cả chứng chỉ tự ký). |
| F12 | `SERVER_BASE_URL` là hằng số biên dịch, hiện trỏ tới `https://datn.thamnguyen.dev` | `include/config.h` (cả 5 bản) | Muốn dữ liệu về server mới thì ít nhất phải đổi hằng số này và nạp lại firmware (câu hỏi Q13). |
| F13 | Chu kỳ đo theo bản firmware: deep-sleep **30 phút**; bản chạy liên tục `SEND_INTERVAL_MS = 15000` (**15 giây**, ghi chú "production: 300000" = 5 phút) | `include/config.h` | Backend không được giả định một chu kỳ cố định; chu kỳ kỳ vọng là thuộc tính của từng node (câu hỏi Q6). |
| F14 | Gateway heartbeat mỗi **5 phút** | `HEARTBEAT_INTERVAL_MS` | Ngưỡng offline Gateway phải lớn hơn hẳn 5 phút. Base đặt đúng 5 phút nên dễ báo offline giả. |
| F15 | `msgCounter` lưu trong RTC memory | `main.cpp` (deep-sleep) | Mất điện → `msgId` về 0; không dùng `msgId` để suy ra mất gói qua lần khởi động lại. |

**Lỗi của backend Base liên quan đến hợp đồng này** (lý do không tái sử dụng):

- Chống trùng chỉ chạy khi có `msg_id` (`telemetryService.js`), mà `gateway-30pin` không gửi → **chống trùng chưa từng hoạt động** với bản này.
- Lưu `pm25: item.pm25 || 0`: cảm biến lỗi (`null`) bị lưu thành **0**; CO2 lỗi thành 400.
- Gói heartbeat toàn số 0 của node bị lưu như số đo thật (PM = 0, AQI = 0).
- Một `node_id` chưa đăng ký trong batch làm **cả batch bị trả 404**, Gateway đẩy lại vào buffer và gửi lại liên tục; dữ liệu của mọi node khác qua Gateway đó bị kẹt.
- Thời điểm đo là `new Date()` lúc lưu.

### 2.3. Ràng buộc từ mô hình ML (đọc từ code, không suy đoán)

| # | Ràng buộc | Giá trị trong code | Nguồn | Hệ quả bắt buộc cho backend |
|---|---|---|---|---|
| M1 | Cột đầu vào | `AQI, pm10, pm2_5, Humidity, Temperature`, theo giờ | `config.BASE_COLUMNS` | Mỗi trạm cần chuỗi theo giờ đủ 5 cột. eCO2, TVOC không vào model. |
| M2 | Thời gian | Naive, giờ địa phương UTC+7. Feature `hour`, `dayofweek`, `month` tính theo giờ này | `data_loading.assert_schema`, `feature_engineering._time_block` | DB lưu UTC; khi dựng feature phải đổi sang `Asia/Ho_Chi_Minh` rồi bỏ múi giờ. Sai bước này làm lệch feature thời gian 7 giờ mà không báo lỗi. |
| M3 | Lịch sử cần có | `required_history_hours = 73` (từ t−72 đến t) | `train.required_history_hours`, metadata | Giữ ít nhất 73 giờ dữ liệu giờ gần nhất cho mỗi trạm. |
| M4 | Xử lý thiếu | Model hiện tại: `no_fill`, rolling `min_periods = window`. **Quyết định Q3: train lại với `ffill3h`** | `config.NAN_POLICY`, `preprocessing.apply_nan_policy` | Backend đọc `nan_policy` trong metadata và gọi đúng `apply_nan_policy`; không tự cài cách lấp. Xem mục 2.4. |
| M5 | Phải có quan sát tại t; độ mới ≤ 2 giờ | `build_inference_features`: lỗi nếu không có dòng tại t hoặc `now − t > 2h` | `predict.py` | Inference chạy ngay sau khi giờ đóng; nếu giờ mới nhất chưa có thì lùi về giờ gần nhất còn trong 2 giờ. |
| M6 | Định nghĩa AQI | Tính từ PM **của từng giờ**; cắt PM2.5 1 chữ số, PM10 số nguyên; nội suy; làm tròn .5 lên; vượt bảng → 500; lấy max | `aqi.compute_aqi`, `meta.aqi_definition` | AQI giờ = `compute_aqi(PM2.5 trung bình giờ, PM10 trung bình giờ)`, gọi đúng hàm Python này. Không lấy trung bình các AQI tức thời, không viết lại công thức bằng SQL. |
| M7 | Định dạng model | 24 file `xgb_AQI_h{3..72}.json` + `.meta.json` (khoảng 20 MB); dự báo bằng `predict(iteration_range=(0, n_trees))`, `n_trees` khác nhau theo horizon (336 ở h=3, 4 ở h=72) | `train.save_model_and_metadata`, `train.predict_with_model` | Bắt buộc dùng `n_trees` trong metadata. |
| M8 | Cách nạp model | `predict.predict()` đọc lại model từ đĩa **cho mỗi horizon, mỗi lần gọi** (khoảng 1 giây) | `predict.predict` → `load_model_and_metadata` | Backend nạp 24 model một lần vào bộ nhớ; tái sử dụng `build_inference_features` và `predict_with_model`. |
| M9 | Phiên bản thư viện | Python 3.12.3, xgboost 3.4.1, pandas 3.0.6, numpy 2.5.3 | `meta.library_versions`, `requirements.txt` | Backend ghim đúng phiên bản xgboost và pandas. |
| M10 | Đóng gói mã ML | Package tên `src` (`from src import config`) | toàn bộ `ml_xgb` | Cần đóng gói lại phần dùng chung trước khi backend import — quyết định ở Phần 02. |
| M11 | Chất lượng theo horizon | 3–24h: tương quan 0,5–0,8. ≥48h: tương quan 0,12–0,33, gần hằng số. Đánh giá thấp đợt AQI ≥ 151 ở mọi horizon | FORESCATING §4.4, §6.3, §6.4, §8 | API trả kèm mức tin cậy theo horizon; không dùng dự báo xa để phát cảnh báo. |
| M12 | Kiểm chứng trên cảm biến thật | Chưa có | FORESCATING §7 | Lưu mọi dự báo và đối chiếu với thực tế để đo sai số thật trên PMS7003. Theo Q2, đây là nguồn dữ liệu duy nhất nên việc đối chiếu càng quan trọng. |
| M13 | Random Forest | 371 MB cho 24 model | FORESCATING §6.8 | Không đưa RF vào production. |
| M14 | Pipeline train | Kiểm tra SHA-256 cố định của `dataset.csv`; mốc split cố định | `data_loading.verify_dataset_hash`, `config.TRAIN_END…` | Train vẫn là việc offline; backend chỉ xuất dữ liệu và nhập model. |

### 2.4. Ràng buộc 73 giờ liên tục — rủi ro số 1

Với model hiện tại (`no_fill`), chỉ cần thiếu 1 giờ của 1 cột trong 73 giờ là `InferenceDataError`. Với chu kỳ 30 phút (2 gói/giờ, LoRa không có ACK), nếu mỗi gói mất độc lập với xác suất `p` thì một giờ thiếu khi cả hai gói mất (`p²`), và xác suất đủ 73 giờ là `(1 − p²)^73`:

| Tỷ lệ mất gói `p` | Xác suất một giờ thiếu | Có thể dự báo (`no_fill`) |
|---|---|---|
| 5% | 0,25% | 83% |
| 10% | 1% | 48% |
| 20% | 4% | 5% |

Đây là mô hình đơn giản để thấy mức độ nhạy; tỷ lệ mất gói thực tế chưa được đo.

**Sau quyết định Q3 (`ffill3h`):** khoảng trống tối đa 3 giờ liên tiếp được lấp bằng giá trị gần nhất (kèm feature `*_is_filled`, `*_age_hours`). Mất gói ngẫu nhiên gần như không còn chặn dự báo: cần 4 giờ liên tiếp thiếu, tức 8 gói liên tiếp mất (`p⁸`, khoảng 10⁻⁸ với `p` = 10%). Những trường hợp vẫn **không** dự báo được:

- Mất dữ liệu từ 4 giờ liên tiếp trở lên: Gateway mất WiFi/điện, node khởi động lại lâu, buffer Gateway đầy (F3).
- Node chưa chạy đủ 73 giờ (mới lắp, hoặc chạy pin chỉ 20,5 giờ).
- Giờ mới nhất cách `now` quá 2 giờ (M5).

Việc train lại model với `ffill3h` thuộc phần ML, cần làm trước khi tích hợp. Backend không phụ thuộc vào chính sách cụ thể vì đọc nó từ metadata.

---

## 3. Đánh giá `ARCHITECHTURE.md`

### 3.1. Phần hợp lý, nên giữ

- Một database duy nhất; bỏ Kafka, Spark, MLflow, ClickHouse, MQTT. Đúng với lưu lượng thực tế.
- FastAPI, cùng Python với ML.
- Tách kiểm tra cảnh báo ra ngoài transaction lưu dữ liệu.
- Tính AQI trên server; bảng ánh xạ cảm biến → feature (mục 3.5) đúng với code.
- Ghi nhận rõ domain shift, pin, độ chính xác cảm biến (mục 7).
- Frontend là SPA tĩnh, chỉ gọi API.
- MCP adapter dùng chung lớp nghiệp vụ với REST; chatbot chỉ diễn đạt số liệu backend trả về.

### 3.2. Phần thừa hoặc quá phức tạp

| Thành phần | Vấn đề | Quyết định |
|---|---|---|
| **MinIO** | Chỉ để lưu 20 MB model và 1 file CSV. Thêm một service, tốn RAM, thêm credential. | **Bỏ.** Model lưu trên volume `model_store/`; DB giữ bảng phiên bản model (đường dẫn, SHA-256, metadata, trạng thái kích hoạt). |
| **Service huấn luyện trong Docker Compose** | Pipeline không train được trên dữ liệu mới nếu không sửa (M14). Đã chốt dùng model train sẵn, backend không train (04/10). | **Bỏ.** Train offline. Backend cung cấp xuất dữ liệu giờ ra CSV đúng schema `dataset.csv`, và nhập/kích hoạt gói model mới. |
| **Continuous Aggregate làm đầu vào inference** | Không lưu được số mẫu và cờ đủ/thiếu theo quy tắc ML; dễ tính AQI sai định nghĩa M6; logic AQI phải viết lại bằng SQL. | **Thay** bằng bảng giờ tường minh do backend tính khi giờ đóng (và tính lại khi có dữ liệu đến muộn), dùng đúng `compute_aqi`. Thiết kế ở Phần 04. |
| **TimescaleDB** | Free tier (Neon, Supabase) chỉ có bản Apache 2: không có `add_retention_policy`, `add_continuous_aggregate_policy`, `time_bucket_gapfill`, nén. Supabase đã ngừng hỗ trợ trên Postgres 17. Quy mô nhỏ: với chu kỳ 30 phút, mỗi node khoảng 17.500 dòng/năm; với chu kỳ 15 giây khoảng 2,1 triệu dòng/năm. | Đề xuất ban đầu là không dùng. **Quyết định 04/10/2026: giữ TimescaleDB** (tự host trên VPS nên có đủ tính năng). Dùng cho hypertable dữ liệu thô, nén, retention, `time_bucket`; dữ liệu giờ cho ML vẫn do backend tính. Chi tiết: [backend_design §3](backend_design.md#3-timescaledb-và-postgis). |
| **PostGIS** | Chỉ để tìm trạm gần nhất trong vài đến vài chục trạm. | Đề xuất ban đầu là không dùng. **Quyết định 04/10/2026: giữ PostGIS** cho tọa độ node, trạm gần nhất, GeoJSON bản đồ, vùng phủ Gateway. |
| **WebSocket và SSE song song** | Dữ liệu chỉ đi một chiều server → trình duyệt. | **Chỉ SSE.** |
| **Tự host Xiaozhi Server cùng VPS** | Bản tối giản của `xiaozhi-esp32-server` cần tối thiểu **2 nhân / 2 GB RAM** khi dùng toàn API, **2 nhân / 4 GB** khi dùng FunASR cục bộ. | **Không tự host** (Q10). Dùng chatbot Xiaozhi có sẵn qua MCP endpoint; backend cung cấp API trợ lý chỉ đọc, một container nhỏ `xiaozhi-bridge` đăng ký hàm lên Xiaozhi. Chi tiết ở [Phần 09](09-xiaozhi-mcp.md). |
| Frontend 3D (deck.gl, React Three Fiber) | Bundle nặng, hiệu ứng hạt bụi không giúp đọc số liệu. Ngoài phạm vi backend. | Xem lại ở Phần 10. |

### 3.3. Phần còn thiếu

Từ 04/10/2026, nội dung các phần 02–08, 11, 12 được gộp vào [backend_design.md](backend_design.md). Cột "Xử lý ở phần" giữ số phần cũ để đối chiếu.

| # | Thiếu | Vì sao quan trọng | Xử lý ở phần |
|---|---|---|---|
| G1 | Hợp đồng JSON Gateway → server | **Đã xác định từ firmware (mục 2.2).** ARCHITECHTURE cần cập nhật theo. | 05 |
| G2 | Xác thực Gateway | Chỉ có `secret` chung (F10); tự đăng ký Gateway không kiểm soát. | 05 |
| G3 | Thời điểm đo, dữ liệu đến muộn | Không có thời gian trong JSON (F2); batch sau sự cố mạng chứa nhiều bản ghi cũ (F3). Ảnh hưởng trực tiếp bảng giờ và dự báo. | 02, 05 |
| G4 | **Định nghĩa giờ tổng hợp**: nhãn giờ, số mẫu tối thiểu, khi nào giờ "đã hoàn tất" | PLAN_REVIEW mục 5 đã nêu nhưng chưa chốt. Lệch nhãn làm lệch toàn bộ feature lag. | 02 |
| G5 | Chống trùng khi không có `msg_id` | F1, F4. | 05 |
| G6 | Phân biệt heartbeat node với số đo | F8. | 05 |
| G7 | Lịch chạy và lưu trữ dự báo | Tính sẵn mỗi giờ để Web, Admin, Xiaozhi đọc cùng một kết quả. | 08 |
| G8 | Quản lý phiên bản model | Kiểm tra tương thích (feature, phiên bản thư viện, `nan_policy`), kích hoạt, quay lui. | 08 |
| G9 | **Theo dõi sai số dự báo thực tế** | Cách duy nhất để biết model dùng được trên PMS7003 (M12). | 04, 08 |
| G10 | **Vòng đời cảnh báo** | Admin của Base hiển thị **83.207 cảnh báo chờ xử lý, 8.321 trang** (Hình 4.11, 4.18). Cần cảnh báo có trạng thái (mở → đã xác nhận → đã đóng), không tạo trùng khi đang mở, tự đóng khi hết sự cố. | 04, 07 |
| G11 | Chất lượng dữ liệu cảm biến | PM10 < PM2.5, nhảy đột ngột, độ ẩm cao làm PMS7003 đo cao, CO2 = 0 khi CCS811 chưa sẵn sàng (F5). Gắn cờ, không xóa. | 04 |
| G12 | Danh tính thiết bị và vị trí | `nodeId` chỉ 1 byte (F9); di dời node làm chuỗi lịch sử lẫn hai vị trí. **Quyết định D2 (04/10/2026): node là trạm như Base, chấp nhận hệ quả này.** | 04 |
| G13 | Trạng thái từng cảm biến | Giá trị `null`/0/65535 cho biết cảm biến nào hỏng (PMS7003, CCS811, AHT10). PLAN yêu cầu Admin quản lý cả sensor. | 04, 07 |
| G14 | Giám sát hệ thống | Trạng thái job, lưu lượng ingest, bản ghi bị loại, phiên bản model đang chạy. | 07 |
| G15 | Sao lưu, thời hạn lưu dữ liệu | Không có trong tài liệu. | 11 |
| G16 | Kiểm thử đối chiếu train/serve | Feature backend tạo ra phải giống hệt feature lúc train trên cùng dữ liệu. | 02, 12 |

### 3.4. Mâu thuẫn giữa các tài liệu

| Vấn đề | Chỗ mâu thuẫn |
|---|---|
| Khóa JSON | Base.pdf (Hình 4.6) và code: `data`. `docs/firmware/gateway.md` của Base: `readings`. |
| Cấu trúc gói LoRa | `docs/firmware/lora-protocol.md` của Base thiếu PM1 (tổng thực tế 16 byte dù ghi 18); `packet.h` có PM1, đúng 18 byte. |
| Chống trùng | Base.pdf mục 5.2.3 nói "hoạt động chính xác trong toàn bộ các kịch bản"; code cho thấy không chạy với `gateway-30pin` (mục 2.2). |
| Mốc dự báo nhấn mạnh | ARCHITECHTURE: 12/24/48/72h. FORESCATING §8: 3/6/12/24h, 48/72h chỉ kèm nhãn "độ tin cậy thấp". PLAN: 3/6/9/12h. Cần chốt (Q7). |
| Hai loại AQI | ARCHITECHTURE §3.3 tính AQI cho từng mẫu thô; model dùng AQI giờ (M6). Giao diện và API phải ghi rõ là loại nào. |
| Train tự động từ DB | ARCHITECHTURE §4 bước 5 mô tả train định kỳ; pipeline khóa hash và mốc split (M14). |
| Dự báo cho Xiaozhi | §3.9 "gọi inference XGBoost" khi hỏi, nhưng tiêu chí nghiệm thu yêu cầu "khớp kết quả REST API". Đọc dự báo đã tính sẵn thì luôn khớp. |
| Ngưỡng offline | ARCHITECHTURE: node 40 phút, Gateway 5 phút. Node: chỉ đúng với chu kỳ 30 phút (F13). Gateway: bằng đúng chu kỳ heartbeat (F14), dễ báo giả. |
| `sampling_interval` trong cấu hình Admin của Base | Không có downlink LoRa nên giá trị này không đến được node. |
| Đường dẫn tham chiếu | ARCHITECHTURE dẫn `docs/NguyenDucTham_DATN_v2_checked.pdf`, `ml_xgb/`, `data/dataset.csv`; thực tế là `docs/Base.pdf`, `ml/ml_xgb/`, `ml/data/dataset.csv`. |

---

## 4. FastAPI có phù hợp và tối ưu không?

### 4.1. Kết luận

**Phù hợp, nên dùng.** Lý do quyết định là ML viết bằng Python: backend Python dùng **chính hàm** tạo feature và tính AQI của lúc train, nên loại được lỗi lệch train/serve. Các điểm yếu của FastAPI đều có cách xử lý đơn giản ở quy mô này (mục 4.3).

### 4.2. Lý do

| Tiêu chí | FastAPI đáp ứng thế nào |
|---|---|
| Khớp với ML | Gọi trực tiếp `compute_aqi`, `apply_nan_policy`, `build_inference_features`, `predict_with_model`; cùng phiên bản pandas/xgboost. Với Node.js (như Base), phải chạy thêm một service Python cho inference. |
| Kiểm tra dữ liệu đầu vào | Pydantic chuẩn hóa payload Gateway ngay ở biên (F5, F7, F8). |
| Tài liệu API | OpenAPI/Swagger tự sinh, dùng chung cho frontend và báo cáo đồ án. |
| Realtime | Hỗ trợ async, SSE qua `sse-starlette`. |
| Xiaozhi/MCP | Hàm MCP viết bằng Python MCP SDK (FastMCP), cùng ngôn ngữ với backend. |
| Tài nguyên | Ước tính sơ bộ (cần đo khi code): API + pandas + xgboost + 24 model khoảng 250–400 MB RAM. Dư sức trên VPS mức trung bình (Q4b). |

### 4.3. Điểm yếu và cách xử lý

| Điểm yếu | Ảnh hưởng | Cách xử lý |
|---|---|---|
| Inference (pandas + xgboost) dùng CPU, chặn event loop nếu chạy trong request | Request khác bị treo | Tính dự báo trong job nền mỗi giờ, chạy trong thread; request chỉ đọc kết quả từ DB. Mỗi trạm khoảng 0,3–0,5 giây cho 24 horizon. |
| Nhiều worker thì trạng thái trong RAM không dùng chung | Chống trùng, job định kỳ, kênh SSE bị nhân bản hoặc lệch | Chống trùng bằng truy vấn/ràng buộc trong DB (không dùng cache RAM như Base); job giữ khóa `pg_advisory_lock`; SSE qua một interface, bản đầu dùng bộ nhớ trong tiến trình, khi cần nhiều worker thì chuyển sang `LISTEN/NOTIFY` của PostgreSQL (không thêm Redis). Bản đầu chạy **1 worker**. |
| Không có trang admin/phân quyền sẵn | Phải tự viết | Admin Dashboard là trang riêng theo yêu cầu, nên đằng nào cũng tự viết. |

Base.pdf (mục 3.4.1) cho rằng Python/FastAPI "hiệu năng hạn chế cho real-time". Ở hệ thống này lưu lượng chỉ vài request mỗi phút, nên hiệu năng framework không phải yếu tố quyết định.

### 4.4. Phương án khác đã cân nhắc

| Phương án | Lý do không chọn |
|---|---|
| Node.js/Express (như Base) | Cần thêm service Python cho inference → hai runtime, hai nơi định nghĩa AQI. |
| Django + DRF | Nặng hơn; admin có sẵn nhưng không hợp với dashboard riêng. |
| Flask | Đồng bộ, không có sẵn kiểm tra dữ liệu và OpenAPI. |
| Litestar | Tương đương FastAPI, cộng đồng và tài liệu ít hơn. |

### 4.5. Thư viện đi kèm (đề xuất, chốt ở Phần 03)

SQLAlchemy 2.0 + Alembic (migration), Pydantic v2 + pydantic-settings, APScheduler (job nền), sse-starlette, PyJWT + băm mật khẩu (argon2 hoặc bcrypt), `mcp` (Python SDK).

---

## 5. Kiến trúc đích

Một **modular monolith**: một ứng dụng FastAPI chia module theo nghiệp vụ, một PostgreSQL, một reverse proxy có HTTPS, chạy bằng Docker Compose trên một VPS mức trung bình (Q4, Q4b).

```text
Sensor Node ×N ──LoRa──▶ Gateway ×M ──HTTPS POST (secret chung, F10/F11)──┐
                                                                         ▼
┌───────────────────────── FastAPI (1 tiến trình) ─────────────────────────┐
│  Cổng thiết bị (giữ đúng đường dẫn firmware):                            │
│      /api/v1/telemetry   /api/v1/telemetry/heartbeat   /api/v1/provision │
│  Cổng ứng dụng:  /api/v1/public   /api/v1/admin   /api/v1/stream (SSE)   │
│                  /api/v1/assistant (chỉ mạng nội bộ, cho xiaozhi-bridge) │
│  ─────────────── Lớp nghiệp vụ dùng chung ────────────────────────────── │
│  ingest · devices · measurements · hourly · forecast · alerts ·          │
│  auth · audit · system                                                    │
│  ─────────────── Job nền (APScheduler + khóa PostgreSQL) ──────────────── │
│  tổng hợp giờ · kiểm tra offline · inference mỗi giờ ·                    │
│  đối chiếu dự báo với thực tế · dọn dữ liệu                               │
│  ─────────────── ML runtime ──────────────────────────────────────────── │
│  gói ML dùng chung (AQI + feature) · 24 model nạp sẵn trong bộ nhớ        │
└───────────────┬──────────────────────────────────────────┬───────────────┘
                ▼                                          ▼
        PostgreSQL (duy nhất)                      model_store/ (volume)
                                                   xgb_AQI_h*.json + meta

Trình duyệt (SPA tĩnh) ──REST + SSE──▶ Nginx (HTTPS) ──▶ FastAPI

Loa Xiaozhi ⇄ Xiaozhi server (dịch vụ có sẵn)
                   ▲ WebSocket MCP endpoint, do xiaozhi-bridge chủ động mở
            xiaozhi-bridge (container nhỏ) ──HTTP nội bộ──▶ FastAPI /api/v1/assistant
```

**Nguyên tắc:**

1. **Một nguồn sự thật cho AQI và feature:** gói ML dùng chung, backend không viết lại công thức.
2. **Giữ đúng hợp đồng firmware** ở cổng thiết bị (đường dẫn, mã trả về, tên trường); mọi chuẩn hóa nằm ở biên ingest.
3. **Dự báo tính sẵn, lưu lại:** Web, Admin, Xiaozhi đọc cùng một bảng dự báo; mọi dự báo được đối chiếu với thực tế khi đến giờ đích.
4. **Không giữ trạng thái quan trọng trong RAM:** chống trùng, cảnh báo, lịch job đều dựa vào DB.
5. **Tách lớp:** router (HTTP) → service (nghiệp vụ) → repository (SQL). API web và API trợ lý gọi cùng service.
6. **Một database:** PostgreSQL + TimescaleDB + PostGIS (quyết định 04/10/2026), image `timescale/timescaledb-ha`.
7. Job nền chạy cùng tiến trình API ở bản đầu; có thể tách thành `worker` riêng từ cùng mã nguồn khi cần.

**Số service phía server:**

| | ARCHITECHTURE hiện tại | Kiến trúc đích |
|---|---|---|
| Bắt buộc | TimescaleDB + PostGIS, MinIO, FastAPI, Nginx, service huấn luyện | PostgreSQL (TimescaleDB + PostGIS), FastAPI, reverse proxy |
| Chatbot | Xiaozhi Server trên cùng máy | `xiaozhi-bridge` (tiến trình Python nhỏ); Xiaozhi server là dịch vụ có sẵn |
| Tổng trên VPS | 6 | 4 |

---

## 6. Khác biệt có chủ đích so với backend của Base

| Khía cạnh | Base (Node.js) | Kiến trúc đích |
|---|---|---|
| Chống trùng | `dedupCache` trong RAM theo `msg_id`, không chạy khi thiếu `msg_id` | Theo `msg_id` khi có, theo nội dung + cửa sổ thời gian khi không có; dựa trên DB |
| Giá trị lỗi | `null` → 0, CO2 lỗi → 400 | Giữ `NULL`, gắn cờ cảm biến lỗi |
| Heartbeat node | Lưu thành số đo 0 | Nhận diện và chỉ cập nhật trạng thái |
| Node lạ trong batch | Từ chối cả batch (404), Gateway gửi lại mãi | Nhận phần hợp lệ, cách ly phần lạ, luôn trả 200 |
| Dữ liệu giờ | Continuous Aggregate trung bình | Bảng giờ có số mẫu, cờ đủ/thiếu, AQI theo định nghĩa ML |
| Cảnh báo | Mỗi lần vượt ngưỡng/offline tạo bản ghi mới, cooldown 15 phút | Cảnh báo có trạng thái, một sự cố là một bản ghi, tự đóng khi hết |
| Cấu hình ngưỡng | Một dòng `alert_configs` cố định cột | Quy tắc cảnh báo dạng bảng (thông số, ngưỡng, phạm vi trạm) |
| AI | Không có | Phiên bản model, dự báo theo giờ, đối chiếu sai số thực tế |
| Realtime | Socket.IO | SSE |
| Chatbot | Không có | API trợ lý chỉ đọc dùng chung lớp nghiệp vụ + hàm MCP đăng ký lên Xiaozhi |

---

## 7. Rủi ro chính

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| Không đủ 73 giờ liên tục → không có dự báo | Cao → Trung bình sau Q3 | `ffill3h` (mục 2.4); hiển thị rõ lý do "chưa đủ dữ liệu" kèm số giờ còn thiếu |
| Model chưa kiểm chứng trên PMS7003, và đây là nguồn duy nhất (Q2) | Cao | Đối chiếu dự báo với thực tế (G9), hiển thị sai số thật trên Admin |
| Sai thời điểm đo sau sự cố mạng (F2, F3) | Trung bình | Ước lượng lại thời điểm khi một batch chứa nhiều bản ghi của cùng node; gắn cờ "thời điểm ước lượng" (Phần 05) |
| Trùng dữ liệu khi không có `msg_id` (F1, F4) | Trung bình | Chống trùng theo nội dung (Phần 05) |
| Một `secret` chung cho mọi Gateway (F10) | Trung bình | Chỉ nhận từ Gateway đã đăng ký và đang bật, giới hạn tần suất, ghi log nguồn gửi (Phần 05) |
| Xiaozhi mất kết nối hoặc dịch vụ Xiaozhi gián đoạn | Thấp | Bridge chạy riêng, tự kết nối lại; không ảnh hưởng ingest, web, cảnh báo (Phần 09) |

---

## 8. Câu hỏi

### 8.1. Đã chốt

| # | Câu hỏi | Quyết định (03/10/2026) |
|---|---|---|
| Q1 | Firmware Gateway giữ nguyên hay được sửa? | **Giữ nguyên firmware Base** (mã trong `base_code.zip`); backend và frontend viết mới hoàn toàn. Hợp đồng ở mục 2.2. |
| Q2 | Dự báo dùng dữ liệu nào? | **Chỉ dữ liệu cảm biến.** Không tích hợp Open-Meteo. |
| Q3 | Xử lý giờ thiếu? | **Train lại model với `ffill3h`**; backend đọc `nan_policy` từ metadata. |
| Q4 | Triển khai ở đâu? | **VPS + Docker Compose.** Ngày 04/10/2026 bổ sung: giữ TimescaleDB + PostGIS; bỏ ràng buộc cấu hình nhẹ nhất, dùng VPS mức trung bình (Q4b). |
| Q10 | Tích hợp Xiaozhi thế nào? (chốt 04/10/2026) | **Dùng chatbot Xiaozhi có sẵn qua MCP endpoint, không tự host.** Chatbot chỉ tra cứu thông tin môi trường và dự báo, **không trả lời thông tin quản trị**. Xem [Phần 09](09-xiaozhi-mcp.md). |

### 8.2. Còn mở

Từ 04/10/2026, các điểm chưa chốt được theo dõi tập trung ở [backend_design.md mục 21](backend_design.md#21-quyết-định-p1p14-và-điểm-còn-chờ) (P1–P14; đã chốt ngày 04/10/2026, còn P1b). Bảng dưới giữ lại để tra nguồn gốc câu hỏi.

| # | Câu hỏi | Phần |
|---|---|---|
| Q5 | Nhãn giờ tổng hợp: đầu khoảng `[h, h+1)` hay cuối khoảng `(h−1, h]`; số mẫu tối thiểu để một giờ hợp lệ | 02 |
| Q6 | Bản firmware nào được dùng thật (`gateway` hay `gateway-30pin`; node deep-sleep 30 phút hay chạy liên tục), chu kỳ đo thực tế và số node/Gateway dự kiến | 02, 04 |
| Q7 | Mốc dự báo hiển thị công khai (3/6/9/12h theo PLAN hay 3/6/12/24h theo FORESCATING); cách hiển thị 48–72h | 08, 10 |
| Q8 | Người xem có cần đăng nhập không; có vai trò nào ngoài admin | 04, 07 |
| Q9 | Kênh thông báo chủ động (Telegram, email) có trong phạm vi không | 07 |
| Q11 | Có cần trạm mô phỏng để demo đa trạm như Base không | 04 |
| Q12 | Thời hạn giữ dữ liệu thô (Base: 3 tháng) và dữ liệu giờ | 04, 11 |
| Q13 | "Giữ nguyên firmware" có cho phép đổi các **hằng số cấu hình** `SERVER_BASE_URL`, `PROVISION_KEY`, `GATEWAY_SECRET` rồi nạp lại không? Nếu không, firmware vẫn gửi về `datn.thamnguyen.dev` (F12). | 05, 11 |

---

## Tham khảo bên ngoài đã kiểm tra

- TimescaleDB trên Neon chỉ hỗ trợ tính năng giấy phép Apache 2: <https://neon.com/docs/extensions/timescaledb>
- TimescaleDB trên Supabase là bản Apache 2 và bị ngừng hỗ trợ trên Postgres 17: <https://supabase.com/docs/guides/database/extensions/timescaledb>
- So sánh bản Apache 2 và Community của TimescaleDB: <https://docs.tigerdata.com/about/latest/timescaledb-editions>
- Yêu cầu cấu hình của `xiaozhi-esp32-server`: <https://github.com/xinnan-tech/xiaozhi-esp32-server>
