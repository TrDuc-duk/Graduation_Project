# Kế hoạch chi tiết và nhật ký triển khai backend

**Cập nhật:** 22/10/2026.
**Phạm vi:** những phần đã code theo thứ tự phát triển ở [backend_modules.md §7](backend_modules.md#7-thứ-tự-phát-triển): Phase 0 (M0 – khung), Phase 1 (M1 – thiết bị + ingest), dashboard demo cảm biến, các bản sửa sau thử nghiệm phần cứng. Quyết định thiết kế nằm ở [README.md](README.md) (nhật ký quyết định); báo cáo tiến độ ở [report-tuan-6.md](../report-tuan-6.md).

---

## 1. Tổng quan tiến độ

| Mốc | Nội dung | Trạng thái |
|---|---|---|
| **M0** Khung | `core`, `/healthz`, `/readyz`, Alembic `0001_base`, CI | ✅ Xong |
| **M1** Thiết bị + ingest | `devices`, `telemetry`, `ingest`, migration `0002`, `0003`, 5 endpoint firmware, job `interval_stats`, script mô phỏng Gateway | ✅ Xong |
| Dashboard demo | API dev chỉ đọc + frontend React/Vite/ECharts, polling 10 giây | ✅ Xong (bản demo, chưa phải trang người dùng F1–F6) |
| Sửa sau thử nghiệm phần cứng | Dải CCS811, migration `0004_ccs811_range`, firmware AHT10/CCS811, frontend qua Nginx trong Compose dev | ✅ Xong (theo [report-tuan-6.md](../report-tuan-6.md)) |
| **M2** Dữ liệu giờ + API công khai | `hourly`, `pipeline` bước 1, `stations`, `realtime` (SSE), `weather` | ⏳ Chưa làm |
| **M3–M8** | Dự báo, xác thực + Admin, cảnh báo, Admin dữ liệu, Xiaozhi, triển khai | ⏳ Chưa làm |

---

## 2. Phase 0 – M0 Khung

| Phần | File | Nội dung |
|---|---|---|
| Phụ thuộc, công cụ | `backend/requirements.txt`, `requirements-dev.txt`, `pyproject.toml` | Ghim phiên bản; ruff (line 120); pytest async, `pythonpath` gồm `../ml/ml_xgb` để import `src.aqi` |
| Cấu hình | `app/core/config.py` | `Settings` (pydantic-settings): DB URL, `GATEWAY_SECRETS` (danh sách), `PROVISION_KEY`, `APP_ROLE`, `SCHEDULER_ENABLED`, `ENABLE_API_DOCS`, `ENABLE_DEV_ENDPOINTS` |
| DB, transaction | `app/core/db.py` | Engine async (psycopg 3), giờ UTC, `statement_timeout` 15 giây; `run_in_transaction()` thử lại khi 40P01/40001/55P03 bằng **tenacity** (tối đa 3 lần, nghỉ 50–200 ms, tổng < 8 giây) |
| Lỗi | `app/core/errors.py` | `AppError` → `{"error": {code, message, details}}`; `DeviceError` → `{"success": false, "error": "…"}` cho cổng thiết bị |
| Thời gian | `app/core/timeutil.py` | `Clock` / `FixedClock` (giả lập trong test), `floor_hour`, đổi giờ Việt Nam |
| Khóa advisory | `app/core/locks.py` | `job_lock` (lớp 1, khóa phiên, nhả trong `finally`), `node_address_locks` (lớp 2, khóa theo địa chỉ tăng dần) |
| Outbox, NOTIFY | `app/core/outbox.py`, `events.py` | `publish()` cùng transaction; `dispatch_once()` lấy sự kiện đầu hàng mỗi `partition_key`, backoff `2^n` giây, quá 10 lần → `failed`; `pg_notify('aqi_events')` |
| Job nền | `app/core/scheduler.py` | **APScheduler**; mỗi lần chạy giữ khóa job và ghi `job_runs` (`ok`/`error`/`skipped`) |
| Cấu hình Admin | `app/core/settings_store.py` | Đọc `app_settings` có cache 30 giây; thiếu khóa thì dùng `DEFAULTS` trong code |
| Rate limit, bảo mật | `ratelimit.py`, `security.py`, `security_events.py` | Thư viện **limits** (bộ nhớ, cửa sổ trượt 1 phút); so sánh secret thời gian hằng; ghi `security_events` |
| Sức khỏe | `app/modules/system/router.py` | `/healthz`; `/readyz` kiểm tra DB + extension `timescaledb`, `postgis` |
| Migration | `migrations/versions/0001_base.py` | DDL nguyên văn [database_design §5.1](database_design.md): auth, audit, `app_settings`, `job_runs`, `security_events`, `outbox_events`, `rate_counters` |
| CI | `.github/workflows/backend.yml` | Dựng DB bằng `docker-compose.dev.yml` → ruff → migration `upgrade → downgrade → upgrade` → pytest |

---

## 3. Phase 1 – M1 Thiết bị + ingest

### 3.1. Migration

| Revision | Nội dung |
|---|---|
| `0002_devices` | `lora_networks` (+ mạng `default`), `gateways`, `station_code_seq`, `nodes`, `node_sensors`, `node_gateway_links` |
| `0003_telemetry` | `ingest_batches`, `measurements`: hypertable, nén, retention (14 / 90 ngày). **Không** có `hourly_recompute_queue` (để sang `0004_hourly` ở M2) |
| `0004_ccs811_range` | Đổi `measurements.tvoc` sang `integer` để lưu đủ dải 0–32768 ppb; tự giải nén/nén lại chunk đã nén |

### 3.2. Module

| Module | File chính | Nội dung |
|---|---|---|
| `devices` | `addressing.py`, `repository.py`, `service.py` | Cấp mã `GW_%03d`, địa chỉ LoRa nhỏ nhất còn trống (bỏ địa chỉ đang dùng và đang cách ly 30 ngày, hết → 409), mã trạm `ST001`; tự tạo Gateway/node lạ ở trạng thái `pending`; chu kỳ hiệu lực (R24); trạng thái node chỉ đổi theo bản ghi mới hơn |
| `telemetry` | `qc.py`, `repository.py`, `service.py` | Cờ `qc_flags` (bit 0–13), `EXCLUDE_MASK = 4864`, `is_state_trusted()`; lưu/tra số đo; log `ingest_batches` (bỏ secret khỏi payload) |
| `ingest` | `normalize.py` | Chuẩn hóa §6.4: tách heartbeat node (6 giá trị = 0), loại giá trị ngoài dải thành `null` + cờ, `aqi_instant` bằng `src.aqi.compute_aqi`, trạng thái cảm biến |
| | `dedup.py` | `payload_hash` = BLAKE2b 64 bit trên giá trị đã chuẩn hóa (số làm tròn 1 chữ số, null → `null`); cửa sổ W; thứ hạng bản sao (Gateway active > pending, thời điểm tin cậy > `TIME_UNRELIABLE`) |
| | `staleness.py` | Batch nghi cũ: `gateway_silent`, `after_rejection` |
| | `timing.py` | Gán `measured_at` §6.6.4 (5 trường hợp, 7 điều kiện dùng `msg_id`, modulo 256), `max_age_s` |
| | `pipeline.py` | Trình tự §6.7 trong một transaction: khóa Gateway → khóa địa chỉ → batch nghi cũ → tra/tạo node → thời điểm → chống trùng → lưu → trạng thái → `ingest_batches`, `security_events`, outbox `measurements_ingested`, NOTIFY |
| | `router.py` | 5 endpoint firmware (bảng 3.3) và các giới hạn tần suất |
| | `jobs.py` | Job `interval_stats` (mỗi giờ): `observed_interval_s`, `observed_interval_iqr_ratio`, `lost_packets_24h` |

### 3.3. Cổng thiết bị (giữ hợp đồng firmware datn-main)

| Endpoint | Thành công | Lỗi |
|---|---|---|
| `POST /api/v1/telemetry` | 200 `{"success": true, "accepted", "duplicates", "heartbeats", "rejected"}` (kể cả bản trùng, thiết bị lạ, node bị từ chối) | 400 sai dạng, 401 sai secret, 413 > 32 KB hoặc > 50 bản ghi, 429 vượt giới hạn, 503 lỗi DB. Mã khác 200 khi secret đúng → đặt `telemetry_rejected_since` |
| `POST /api/v1/telemetry/heartbeat` | 200 `{"success": true, "message": "Heartbeat OK"}` | 401, 429, 503 |
| `POST /api/v1/provision/gateway` | 201 `{"success": true, "data": {id, name, location_desc, status}}` | Thiếu key 401, sai key 403, 400, 429 |
| `GET /api/v1/provision/gateways` | 200, chỉ Gateway `active` | 401, 403, 429 |
| `POST /api/v1/provision/node` | 201, `data` có `id` (`NODE_%03d`), `node_numeric_id`, `station_code` | 400 Gateway không hợp lệ, 409 hết địa chỉ |

Giới hạn tần suất: 120 request/phút mỗi Gateway đã biết; 20 request lỗi/phút mỗi IP; 6000 request/phút toàn hệ thống (503); provisioning 10 request/phút mỗi IP.

### 3.4. Script mô phỏng

`backend/scripts/simulate_gateway.py`: mô phỏng buffer 10 gói, xả mỗi 30 giây, giữ batch khi lỗi, heartbeat 5 phút; tùy chọn bản `gateway` / `gateway-30pin`, mất mạng, gửi lại batch.

---

## 4. Dashboard demo cảm biến

### 4.1. API dev chỉ đọc

Module `app/modules/dev` (router → service, đọc qua `devices.service` và `telemetry.service`). Chỉ được gắn khi `ENABLE_DEV_ENDPOINTS=true`; cờ này chỉ bật trong `docker/docker-compose.dev.yml`, tắt thì trả 404. API công khai không thay đổi.

| Endpoint | Trả về |
|---|---|
| `GET /api/v1/dev/nodes` | Mọi node chưa `retired` (kể cả `pending`), Gateway gần nhất (`online` theo `gateway_offline_after_s`), độ mới dữ liệu (`stale_after_s` = `offline_after_s` của node hoặc `default_node_offline_after_s` = 3900) |
| `GET /api/v1/dev/nodes/{id}/readings?hours=1\|6\|24` | Số đo còn hiệu lực trong khoảng (tối đa 20.000 điểm), số đo mới nhất, đơn vị, cờ `quarantined` / `time_unreliable`; giá trị khác 1/6/24 → 422 |

### 4.2. Frontend (`frontend/`)

- React 19 + Vite 8 + TypeScript 7 + ECharts 6, font Be Vietnam Pro tự host, icon Lucide; giao diện sáng, tiếng Việt, responsive (đã kiểm tra 1366 px và 390 px).
- Lấy dữ liệu bằng `fetch` + hook `usePolling` (10 giây, dừng khi tab ẩn); chưa chốt FE1.
- Thẻ PM2.5, PM10 (µg/m³), eCO₂ (ppm), TVOC (ppb), nhiệt độ (°C), độ ẩm (%), pin (%); thẻ AQI chỉ hiện khi backend trả `aqi_instant`.
- Ba biểu đồ: PM2.5/PM10 cùng trục; khí và nhiệt-ẩm hai trục y riêng có đơn vị; null để đứt quãng.
- Trạng thái: đang tải, mất kết nối, dữ liệu cũ, chưa có dữ liệu, node chờ duyệt, dữ liệu cách ly, API dev chưa bật. Giá trị null hiển thị "—".
- Chạy bằng Vite (`npm run dev`, proxy `/api`) hoặc bản build qua Nginx trong Compose dev (`docker/nginx/dev.conf`).

---

## 5. Sửa sau thử nghiệm với phần cứng thật

Chi tiết và bằng chứng ở [report-tuan-6.md §3](../report-tuan-6.md) và [firmware/sensor-node-30pin/DIAGNOSTICS.md](../../firmware/sensor-node-30pin/DIAGNOSTICS.md).

| Vấn đề | Cách xử lý |
|---|---|
| AHT10 trả nhiệt độ lặp và độ ẩm 0 % khi dùng chung bus I²C với CCS811 và OLED (lỗi phát sinh ngay tại node, firmware không bắt được vì chỉ kiểm tra NaN) | Sửa firmware `sensor-node-30pin`: reset AHT10 trước lượt đo, kiểm tra ACK/đủ byte/busy/hiệu chuẩn, lỗi trả sentinel. Backend giữ nguyên quy tắc độ ẩm |
| Backend và firmware cũ loại nhầm CCS811 (eCO₂ > 8192, TVOC > 1187); giá trị 0 lẫn giữa "chưa có mẫu" và "lỗi" | Dải mới theo datasheet: eCO₂ 400–29206 ppm, TVOC 0–32768 ppb (`normalize.py`); migration `0004_ccs811_range` |
| Frontend phải chạy riêng bằng Vite | Compose dev thêm service `frontend` (Nginx, cùng origin `/api/`), healthcheck cho `api` và `frontend` |

---

## 6. Khác biệt so với thiết kế đã ghi nhận

| Điểm | Thiết kế | Đã làm | Lý do |
|---|---|---|---|
| Kiểm tra ranh giới module, kiểu | import-linter, mypy strict | Không dùng | Quyết định 15/10 (đủ nghiệp vụ, gọn hạ tầng) |
| Rate limit | `memory` + `postgres` | Chỉ bộ nhớ (thư viện `limits`) | Như trên; chỉ chạy một tiến trình API |
| Router cổng thiết bị | `/provision/*` ở `devices` | Cả 5 endpoint ở `ingest/router.py` | Provisioning phải ghi `ingest_batches` (của `telemetry`, tầng trên `devices`); nghiệp vụ vẫn ở `devices/service.py` |
| Job `interval_stats` | Module `devices` | `ingest/jobs.py` | Phải đọc `measurements`/`ingest_batches`; kết quả ghi qua `devices.service` |
| `hourly_recompute_queue` | Ingest xếp hàng tính lại giờ từ M1 | Chưa có; đánh dấu `TODO(M2)` | Quyết định 15/10 |
| `app_settings` mặc định | Seed ở `0008` (M2) | `DEFAULTS` trong `settings_store.py` | Seed thuộc M2 |
| Test | Mỗi test rollback transaction | Xóa sạch dữ liệu sau mỗi test, **chỉ chạy trên DB tên `*_test`** (hoặc `ALLOW_TEST_DB_WIPE=1` ở CI) | Test cần commit thật (khóa, đồng thời); tránh xóa DB `aqi` đang nhận số đo |
| Router frontend | React Router | Một trang, chưa có router | Phạm vi demo |

---

## 7. Kiểm thử

- Backend có 113 hàm test (124 trường hợp kể cả `parametrize`): unit (chuẩn hóa, hash, thời điểm, batch nghi cũ, địa chỉ, chu kỳ), integration (provisioning, telemetry với payload firmware datn-main, chống trùng giữa Gateway, đồng thời, rate limit, outbox, job, API dev), schema (migration hai chiều, CHECK, hypertable/policy, chunk nén, quyền `aqi_app`).
- Fixture payload thật của firmware: `backend/tests/fixtures/firmware.py`.
- Chạy trên DB riêng `aqi_test` (tạo bằng superuser như `docker/db/100_aqi_roles.sh`):

  ```bash
  cd backend
  set -a && . ../docker/.env && set +a
  DATABASE_URL=postgresql+psycopg://aqi_app:$DB_APP_PASSWORD@localhost:5432/aqi_test \
  MIGRATION_DATABASE_URL=postgresql+psycopg://aqi_migrator:$DB_MIGRATOR_PASSWORD@localhost:5432/aqi_test \
  .venv/bin/pytest -q
  ```

- Frontend: `npm run build` (kiểm tra kiểu TypeScript); chưa có test tự động (chờ FE5).

---

## 8. Việc còn mở

| Việc | Ghi chú |
|---|---|
| FK `measurements.gateway_id` không có index | database_design §13 yêu cầu FK trên bảng lớn có index. **Cần quyết định:** thêm `ix_measurements_gateway` hay ghi là ngoại lệ |
| `audit_logs` cho provisioning | Chờ module `audit` (M4) |
| Sự kiện bảo mật `node_unusual_gateway`, `node_rate_anomaly` | Chưa làm |
| Dispatcher outbox | Đang quét mỗi 5 giây, chưa dùng `LISTEN outbox` |
| Nhả khóa khi trả kết nối về pool | Chưa gọi `pg_advisory_unlock_all()`; khóa job đã nhả trong `finally` |
| Giá trị `time_source = 'device'` | Chưa làm vì firmware chưa gửi thời điểm đo |
| FE1–FE5 (data layer, state, UI kit, tile bản đồ, test) | Vẫn chờ chốt ở [frontend_design §12](frontend_design.md) |
| Phần cứng | Tách AHT10 sang bus riêng, theo dõi dài hạn, chạy lại toàn tuyến node → LoRa → Gateway → backend → dashboard |
| Mốc tiếp theo | M2: `hourly`, đóng giờ, `/public/*`, SSE, `weather` |

---

## 9. Môi trường dev

| Thành phần | Địa chỉ / lệnh |
|---|---|
| DB | `docker compose -f docker/docker-compose.dev.yml up -d db` (cổng `127.0.0.1:5432`) |
| Backend | Container `api`, cổng `API_PORT` (máy hiện tại 8001): Swagger `/api/docs`, `/readyz` |
| Frontend | Service `frontend` hoặc `cd frontend && PATH=~/.local/node-v22/bin:$PATH npm run dev` → <http://127.0.0.1:5173> |
| Migration | `docker compose -f docker/docker-compose.dev.yml run --rm api alembic upgrade head` |
| Node.js | Node 22 LTS cài ở `~/.local/node-v22` (không dùng sudo) |
| Bí mật | `docker/.env`, `backend/.env`: không commit; `.dockerignore` bỏ `**/.env` |

---

## 10. Giao diện kiểu IQAir và API trợ lý (23/10/2026, theo `PLAN_NOW.md`)

Mỗi mục một commit. Kiểm tra giao diện bằng Chrome headless (CDP): tương tác, ảnh desktop 1366 px và mobile 390 px.

### 10.1. F1 – Topbar
- Pill trượt tới tab đang hover/focus (nền tối, chữ trắng), về tab đang chọn (nền xanh lá nhạt); không có dropdown/overlay.
- Menu điện thoại: mờ dần + trượt 250 ms; đóng khi chạm ra ngoài, Esc (trả focus về ☰) hoặc đổi trang.
- Màu chủ đạo xanh lá nhạt `#4ade80` làm nền; chữ/viền trên nền trắng dùng `#15803d`, chữ trên nền xanh dùng `#14532d` (đủ tương phản).

### 10.2. F2 – Tổng quan
- Phần đầu trang có nền loang màu theo mức AQI; thẻ AQI gọn (ô số, nhãn, mặt biểu cảm, PM2.5, nhiệt độ, độ ẩm, giờ đo).
- Thẻ thông số (PM2.5, PM10, nhiệt độ, độ ẩm; eCO₂, TVOC nhỏ hơn), thẻ thiết bị, dải so sánh PM2.5 với hướng dẫn năm của WHO (5 µg/m³), khuyến nghị sức khỏe theo mức (nội dung soạn sẵn theo US EPA), thang AQI dọc, biểu đồ.
- Khung nội dung 1056 px trên nền trắng, cỡ chữ gốc 15 px. Node đang xem nằm trên URL (`?node=`).

### 10.3. F3 – Bản đồ
- Leaflet 1.9.4 (thư viện bản đồ phổ biến, không dùng react-leaflet). Marker tròn màu AQI, viền đứt khi dữ liệu cũ; popup nội dung React qua portal (AQI, PM2.5, PM10, nhiệt độ, giờ đo, liên kết Tổng quan/Lịch sử); nút toàn màn hình, về các trạm, zoom; chú giải 6 mức; danh sách trạm xếp theo AQI.
- Tile: `tile.openstreetmap.org` bị DNS mạng dev trả về `127.0.0.1`; CARTO đã bắt buộc API key. Dùng tile OSM kiểu HOT của OSM France (không cần key), đổi được bằng `VITE_MAP_TILE_URL`.
- API dev: `NodeOut` thêm `district`, `latitude`, `longitude`, `latest` (chỉ bổ sung trường).
- `scripts/set_station.py` (chạy `python -m scripts.set_station` trong `backend/`): đặt tên, khu vực, tọa độ; `--activate` duyệt trạm pending; `--default` đặt `app_settings.default_station_id`. Chỉ sửa `nodes`, `app_settings`; không đụng số đo. **Chưa chạy trên DB thật**: cần tọa độ thật của NODE_076.
