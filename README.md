# Hệ thống IoT quan trắc và dự báo chất lượng không khí (AQI)

Đồ án tốt nghiệp. Mạng cảm biến LoRa đo bụi mịn, khí và nhiệt ẩm; backend lưu trữ, tính AQI theo US EPA từ PM2.5/PM10 và dự báo AQI 3–72 giờ bằng model XGBoost train sẵn. Kết quả hiển thị trên web và trả lời bằng giọng nói qua chatbot Xiaozhi.

```text
Sensor Node ×N ──LoRa 433 MHz──▶ Gateway ──HTTPS──▶ Nginx ──▶ API (FastAPI) ──▶ PostgreSQL + TimescaleDB + PostGIS
Trình duyệt ◀──REST · SSE──▶ Nginx ──▶ API          xiaozhi-bridge ──▶ API trợ lý ──▶ Xiaozhi (MCP)
```

Kiến trúc chi tiết: [docs/ARCHITECHTURE.md](docs/ARCHITECHTURE.md).

## Thành phần

| Thư mục | Nội dung | Công nghệ |
|---|---|---|
| [`firmware/`](firmware/) | Sensor node (PMS7003, CCS811, AHT10/DHT22) và Gateway LoRa → HTTPS | ESP32, PlatformIO/Arduino |
| [`backend/`](backend/) | Cổng thiết bị (5 endpoint firmware), chuẩn hóa, chống trùng, ước lượng thời điểm đo, API web, API trợ lý, job nền | Python 3.12, FastAPI, SQLAlchemy async, Alembic, APScheduler |
| [`frontend/`](frontend/) | Web kiểu IQAir: Tổng quan, Bản đồ, Lịch sử | React 19, Vite, TypeScript, ECharts, Leaflet |
| [`ml/`](ml/) | Dữ liệu, tiền xử lý, feature, train/đánh giá model dự báo AQI | XGBoost (chính), Random Forest (so sánh) |
| [`xiaozhi-bridge/`](xiaozhi-bridge/) | Đăng ký 4 tool MCP để Xiaozhi tra cứu AQI qua API trợ lý | Python, `websockets` |
| [`docker/`](docker/) | Docker Compose dev và production, Nginx + Certbot, script vai trò DB, sao lưu | Docker Compose |

## Tiến độ

| Mốc | Nội dung | Trạng thái |
|---|---|---|
| M0 | Khung backend, migration, CI | Xong |
| M1 | Thiết bị, ingest từ firmware, mô phỏng Gateway | Xong |
| — | Giao diện web 3 trang (dữ liệu qua API dev) | Xong |
| M7 | API trợ lý và `xiaozhi-bridge` | Xong, chưa thử với Xiaozhi thật |
| M2–M4 | Dữ liệu giờ, API công khai, SSE, dự báo, đăng nhập và trang quản trị | Đang làm |

## Chạy trên máy dev

Cần Docker (có Compose plugin). Backend, DB và frontend chạy trong container:

```bash
cp -n docker/.env.example docker/.env      # điền mật khẩu DB, JWT_SECRET, GATEWAY_SECRETS, PROVISION_KEY
cd docker
docker compose -f docker-compose.dev.yml up -d --wait db
docker compose -f docker-compose.dev.yml run --rm api alembic upgrade head
docker compose -f docker-compose.dev.yml up -d --build --wait api frontend
```

- Web: <http://localhost:5173>
- API và Swagger: <http://localhost:8000/api/docs> (đổi cổng bằng `API_PORT`)

Triển khai lên VPS (HTTPS, Let's Encrypt, sao lưu): [docker/README.md](docker/README.md).

## Cấu hình và bí mật

- Mọi bí mật nằm trong `docker/.env` (không commit): mật khẩu DB, `JWT_SECRET`, `GATEWAY_SECRETS`, `PROVISION_KEY`, `ASSISTANT_TOKEN`, `WEATHER_API_KEY`, `MCP_ENDPOINT`. Danh sách biến ở [docker/.env.example](docker/.env.example).
- Khóa trong firmware nằm ở `firmware/*/include/secrets.h` (không commit), tạo từ `secrets.example.h`; xem [firmware/README.md](firmware/README.md).
- Sinh secret ngẫu nhiên: `openssl rand -hex 24`.

## Kiểm thử

```bash
# Backend: chạy trên DB riêng tên *_test (test xóa dữ liệu sau mỗi lần chạy)
cd backend
set -a && . ../docker/.env && set +a
DATABASE_URL=postgresql+psycopg://aqi_app:$DB_APP_PASSWORD@localhost:5432/aqi_test \
MIGRATION_DATABASE_URL=postgresql+psycopg://aqi_migrator:$DB_MIGRATOR_PASSWORD@localhost:5432/aqi_test \
.venv/bin/pytest -q

# Cầu nối Xiaozhi
cd xiaozhi-bridge && python -m unittest discover -s tests

# Frontend: kiểm tra kiểu và build
cd frontend && npm ci && npm run build
```

CI (GitHub Actions) chạy ruff, migration hai chiều và pytest trên `timescaledb-ha`.

## Demo web không cần cảm biến

Khi backend và frontend đang chạy, mở terminal tại thư mục dự án:

```bash
python3 backend/scripts/demo_sensors.py
```

Script chỉ cần Python 3.10+, không cần cài thư viện. Tự đăng ký 1 gateway và 3 trạm
`DEMO`, gửi số đo mỗi 5 giây, dùng lại ID đã lưu khi chạy lại. Mở web (dev mặc định
`http://localhost:5173`), chọn trạm `DEMO`; web tự cập nhật mỗi 10 giây. Chạy trước
vài phút để biểu đồ có dữ liệu. Nhấn **Ctrl+C** để dừng.

```bash
# Giữ mức ô nhiễm cao trong 10 phút
python3 backend/scripts/demo_sensors.py --scenario polluted --minutes 10

# Web/backend ở máy khác (cần cấu hình khóa đúng với máy đích)
python3 backend/scripts/demo_sensors.py --base https://your-host --env-file /path/to/demo.env

# Dùng gateway và node đã có
python3 backend/scripts/demo_sensors.py --gateway-id GW_001 --node-ids NODE_001 NODE_002

# Xem dữ liệu mẫu, không gửi lên server
python3 backend/scripts/demo_sensors.py --dry-run
```

Các chế độ: `cycle` (mặc định, dao động theo chu kỳ 3 phút), `clean`, `moderate`,
`polluted`, `mixed` (trạm đầu ô nhiễm, các trạm còn lại tốt). Script đọc
`GATEWAY_SECRETS`, `PROVISION_KEY`, `API_PORT` từ môi trường
hoặc `docker/.env` (nếu thiếu thì `backend/.env`); thiếu khóa thì script dừng
và báo lỗi. Cổng mặc định `8001`. Dùng `--base` để chọn địa chỉ khác.

Dashboard cần `ENABLE_DEV_ENDPOINTS=true` (đã bật trong `docker-compose.dev.yml`).
Thiết bị mới ở trạng thái chờ duyệt; dashboard dev vẫn hiển thị số đo thô nhưng dữ
liệu cách ly chưa dùng cho tổng hợp/ML. Script gửi dữ liệu vào database thật và
không tự tạo lịch sử quá khứ. Nếu đã reset database, xóa `backend/.demo-sensors.json`
để đăng ký lại; dùng `--state FILE` riêng cho mỗi backend. Không chạy hai bản script
cùng một bộ thiết bị đồng thời.

## Firmware và xử lý lỗi cảm biến

Xem [README firmware](firmware/README.md) để chạy thử IoT trong LAN, cấu hình Gateway và đọc ghi nhận lỗi AHT10 đứng nhiệt độ/độ ẩm khi CCS811 bắt đầu có dữ liệu: nguyên nhân, bản sửa ngày 16/10/2026 và kết quả kiểm chứng.
