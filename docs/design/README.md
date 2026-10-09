# Thiết kế hệ thống — chỉ mục

Bộ tài liệu thiết kế backend, database, API, frontend và tích hợp Xiaozhi cho hệ thống quan trắc và dự báo AQI. Tổng quan thành phần và công nghệ: [`docs/ARCHITECHTURE.md`](../ARCHITECHTURE.md).

Ký hiệu trạng thái: **Chưa bắt đầu** · **Nháp** (đang chờ chốt) · **Đã chốt** · **Đang dùng để code**.

## Tài liệu

| Tài liệu | Nội dung | Trạng thái |
|---|---|---|
| [01-danh-gia-kien-truc.md](01-danh-gia-kien-truc.md) | Đánh giá kiến trúc cũ, hợp đồng firmware thực tế, ràng buộc ML, đánh giá FastAPI | Đã chốt |
| [backend_design.md](backend_design.md) | **Thiết kế backend để code.** Gồm: TimescaleDB + PostGIS, ingest, dữ liệu giờ, dự báo, cảnh báo, API, **UI flow (mục 12)**, bảo mật, triển khai, kiểm thử, lộ trình M0–M8 | Đang dùng để code; P1–P15, R1–R30 đã chốt; còn P1b, P16 (mục 21) |
| [database_design.md](database_design.md) | **Schema DB để code:** 32 bảng theo module, DDL đầy đủ, index và truy vấn chính, TimescaleDB, mã dùng chung, địa chỉ LoRa, dung lượng, migration, vai trò DB, kiểm thử schema | Đang dùng để code |
| [backend_modules.md](backend_modules.md) | **Chia module để dev:** 18 module, bảng sở hữu, giao diện công khai, đồ thị phụ thuộc, cấu trúc thư mục, quy tắc code, thứ tự phát triển và việc đầu tiên của M0 | Đang dùng để code |
| [frontend_design.md](frontend_design.md) | Thiết kế frontend cơ bản: công nghệ, cấu trúc mã nguồn, route, tầng dữ liệu, i18n, quy ước hiển thị, lộ trình FE-M0–FE-M4 | Đang dùng để code; FE1–FE5 chờ chốt (mục 12) |
| [09-xiaozhi-mcp.md](09-xiaozhi-mcp.md) | Tích hợp Xiaozhi qua MCP endpoint: API trợ lý chỉ đọc, container `xiaozhi-bridge` | Đã chốt; X6 thử khi code |
| 10 — Visualization | Thiết kế hình ảnh: bố cục, màu, kiểu biểu đồ, bản đồ, hiệu ứng 3D | Chưa bắt đầu |

## Điểm đang chờ quyết định

- Backend: [backend_design.md mục 21](backend_design.md#21-quyết-định-p1p14-và-điểm-còn-chờ) — P1b (quy ước giờ của nguồn dữ liệu train cũ), P16 (khoảng dự báo hiệu chỉnh; từ review R15).
- Sửa theo `PLAN_REVIEW.md`: [backend_design.md mục 22](backend_design.md#22-rà-soát-theo-plan_reviewmd-04102026) — đợt 1 (R1–R15) và đợt 2 (R16–R30) đã chốt.
- Frontend: [frontend_design.md mục 12](frontend_design.md#12-các-điểm-cần-bạn-quyết-định) — FE1–FE5.

## Sổ quyết định

| Ngày | Mã | Quyết định | Tài liệu |
|---|---|---|---|
| 03/10/2026 | Q1 | Giữ nguyên firmware Base (`base_code.zip`); backend và frontend viết mới hoàn toàn | 01 |
| 03/10/2026 | Q2 | Dự báo chỉ dùng dữ liệu cảm biến; không dùng Open-Meteo cho dự báo | 01 |
| 03/10/2026 | Q3 | Backend đọc `nan_policy` từ metadata model; khuyến nghị train lại một lần với `ffill3h` trên dataset hiện có | 01 |
| 03/10/2026 | Q4 | Triển khai trên VPS nhỏ bằng Docker Compose | 01 |
| 03/10/2026 | — | Kiến trúc modular monolith FastAPI + một database + reverse proxy HTTPS. Bỏ MinIO, service huấn luyện, WebSocket; realtime bằng SSE | 01 |
| 04/10/2026 | Q10 | Dùng chatbot Xiaozhi có sẵn qua MCP endpoint, không tự host. Chatbot chỉ tra cứu môi trường và dự báo, không trả lời thông tin quản trị | 09 |
| 04/10/2026 | — | Hàm MCP gọi API trợ lý chỉ đọc `/api/v1/assistant/*` (không đọc DB, không lấy từ web); mã đăng ký hàm chạy trong container `xiaozhi-bridge` | 09 |
| 04/10/2026 | — | Dùng file model đã train sẵn; backend chỉ nạp model và dự báo từ dữ liệu lịch sử, không train | backend_design |
| 04/10/2026 | — | Giữ **TimescaleDB** (time-series) và **PostGIS** (không gian) | backend_design §3 |
| 04/10/2026 | D1 | Dữ liệu giờ do backend tính bằng hàm Python của ML; không dùng continuous aggregate | backend_design §7 |
| 04/10/2026 | D2 | Node là trạm (như Base); tọa độ PostGIS nằm trên node | backend_design §4.1 |
| 04/10/2026 | D2b | Xóa node = ngưng hoạt động, giữ dữ liệu; chỉ xóa hẳn node chưa có dữ liệu | backend_design §5.3 |
| 04/10/2026 | D3 | Thiết bị có ID lạ: tự tạo trạng thái chờ duyệt, vẫn lưu dữ liệu, chưa công khai | backend_design §6.3 |
| 04/10/2026 | D4 | Chống trùng theo nội dung + cửa sổ thời gian (1 giờ nếu có `msg_id`) | backend_design §6.5 |
| 04/10/2026 | S1 | Giữ secret/provision key của firmware (đã công khai cùng mã nguồn Base). Bù bằng: cách ly dữ liệu qua Gateway chưa duyệt, giới hạn tần suất, ghi sự kiện bảo mật | backend_design §14.1 |
| 04/10/2026 | S2 | Quy tắc bảo mật ở mức cơ bản, nằm trong mục 14 của backend_design | backend_design §14 |
| 04/10/2026 | — | Frontend giữ như ARCHITECHTURE: React + Vite + TypeScript, React Router, ECharts, deck.gl + MapLibre, React Three Fiber | frontend_design |
| 04/10/2026 | U1 | Trang chủ "Trạm gần bạn" như Base (xin vị trí → trạm gần nhất; từ chối thì dùng trạm mặc định) | backend_design §12 |
| 04/10/2026 | U2 | Giao diện tiếng Việt + English như Base; backend trả mã + nhãn đã dịch theo `Accept-Language` | backend_design §11.1 |
| 04/10/2026 | U3 | Thẻ thời tiết như Base, lấy từ OpenWeatherMap qua backend, chỉ để hiển thị | backend_design §11.11 |
| 04/10/2026 | Q4b | Bỏ ràng buộc "nhẹ nhất, chạy được VPS cấu hình thấp/free tier"; triển khai trên VPS mức trung bình, tham chiếu 2 vCPU / 4 GB RAM / 80 GB SSD. Sửa `PLAN.md` mục 11 | 01, backend_design §17.1 |
| 04/10/2026 | — | Giữ một container `api` (1 tiến trình uvicorn) chạy cả API và job nền | backend_design §2 |
| 04/10/2026 | P5 | Reverse proxy: Nginx + Certbot như Base và ARCHITECHTURE cũ (không dùng Caddy) | backend_design §17.1 |
| 04/10/2026 | P8 | Dữ liệu thô giữ 90 ngày (nén sau 14 ngày); dữ liệu giờ, dự báo giữ lâu dài; log ingest 14 ngày | backend_design §3.1 |
| 04/10/2026 | — | Vẽ lại `docs/architecture.svg`; viết lại `ARCHITECHTURE.md` ngắn gọn theo thành phần và công nghệ | ARCHITECHTURE |
| 04/10/2026 | P1 | Dữ liệu giờ: cửa sổ `(h−1, h]` mang nhãn `h`; tạm ≥ 1 mẫu hợp lệ/biến, kèm số mẫu và độ phủ; ghi rõ các mốc thời gian của dự báo; test không rò rỉ dữ liệu. Quy ước cho ML chờ P1b | backend_design §7, §8.4 |
| 04/10/2026 | P2 | Thời điểm đo: lùi theo chu kỳ node khi firmware không gửi thời điểm; lưu riêng `received_at`/`measured_at`; không cộng thời gian để tránh trùng khóa (P2a: khóa `(id, measured_at)`); batch nghi chứa dữ liệu cũ gắn `TIME_UNRELIABLE`, loại khỏi tổng hợp (P2b); chu kỳ chưa xác định thì không lùi (P2c); dùng `msg_id` có điều kiện (P2d) | backend_design §6.6 |
| 04/10/2026 | P3 | Giờ `t` thiếu: thêm dòng NaN, để `nan_policy` quyết định | backend_design §8.4 |
| 04/10/2026 | P4 | Import trực tiếp code ML; matplotlib import muộn trong phần vẽ của `evaluate.py`; kèm 3 kiểm tra | backend_design §8.2 |
| 04/10/2026 | P6 | Công khai đủ 24 mốc 3–72 giờ, kèm nhãn độ tin cậy | backend_design §8.6 |
| 04/10/2026 | P7 | Vai trò `admin` + `operator` | backend_design §11.8 |
| 04/10/2026 | P9 | Cảnh báo mặc định theo AQI giờ + thiết bị; cảnh báo theo dự báo tắt | backend_design §9.2 |
| 04/10/2026 | P10 | Có trạm mô phỏng, luôn gắn nhãn | backend_design §12.4 |
| 04/10/2026 | P11 | Thông báo Telegram: mức ≥ warning, khi mở và khi đóng | backend_design §9.4 |
| 04/10/2026 | P12 | Access JWT 30 phút + refresh token xoay vòng trong cookie `HttpOnly` | backend_design §11.7 |
| 04/10/2026 | P13 | Thiết bị đăng ký qua provisioning ở trạng thái chờ duyệt | backend_design §6.8 |
| 04/10/2026 | P14 | Xóa Gateway = ngưng hoạt động, giữ dữ liệu | database_design §9 |
| 04/10/2026 | X5, Q7 | Xiaozhi: không nêu trạm thì dùng `default_station_id`; mốc dự báo theo P6 | 09 |
| 04/10/2026 | R1–R15 | Sửa thiết kế theo `PLAN_REVIEW.md`: đường ống giờ lưu trong DB, outbox, chống trùng theo thứ hạng, khóa theo thứ tự, `double precision`, phiên bản model, lưu đầu vào dự báo, SSE qua LISTEN/NOTIFY, sửa lệnh Certbot, test tách lớp. **Chưa duyệt**; R5 thành P15, phần mới của R15 thành P16 | backend_design §22 |
| 04/10/2026 | R1–R15 | Duyệt toàn bộ các sửa theo review; ngưỡng tự đặt (mất mẫu ≤ 1%, 50 SSE/IP, chạy bù 24 giờ) giữ làm mặc định | backend_design §22 |
| 04/10/2026 | P15 | B: tách ID nội bộ `nodes.id` khỏi địa chỉ firmware; địa chỉ `(mạng LoRa, 1–255)` duy nhất trong node chưa `retired`, nhả sau 30 ngày cách ly; node vẫn là trạm (không chọn C) | backend_design §4.1, database_design §9 |
| 04/10/2026 | — | Mã trạm công khai dạng `ST001` (không đổi, không tái sử dụng) | database_design §9 |
| 04/10/2026 | — | Tách tài liệu: `database_design.md` (schema) và `backend_modules.md` (module); backend_design mục 5, 16 chỉ còn liên kết | README |
| 04/10/2026 | R20 | Phiên đăng nhập: JWT mang `sid`, mỗi request Admin kiểm tra phiên (thu hồi có hiệu lực ngay); refresh đồng thời có khoảng ân hạn 30 giây; dùng lại refresh token cũ → thu hồi **một** phiên; đổi mật khẩu, vô hiệu hóa → thu hồi mọi phiên | backend_design §11.7 |
| 04/10/2026 | R26 | Cảnh báo AQI giờ là một cảnh báo nâng/hạ mức warning ↔ critical (thay hai quy tắc riêng) | backend_design §9.1–9.2 |
| 04/10/2026 | R29 | Đầu vào dự báo: 184 feature giữ lâu dài; dòng giờ đã dùng giữ 90 ngày | backend_design §8.4, database_design §5.5 |
| 04/10/2026 | R23 | Dự báo cũ: hiện bản thành công gần nhất ≤ 6 giờ với `status: stale`, chỉ các mốc tương lai; quá 6 giờ thì ẩn số, hiện lý do | backend_design §11.5 |
| 04/10/2026 | R16–R30 | Sửa thiết kế theo `PLAN_REVIEW.md` đợt 2: chạy bù dùng thời điểm phát hành giả lập, outbox tuần tự theo node + mốc đã xử lý, cách ly trạng thái node, rate limit theo Gateway, as-of theo `trusted_at`/`superseded_at`, lần chạy/lần thử dự báo, `msg_id` modulo và học chu kỳ, `nginx.conf` riêng, coverage, Telegram ít nhất một lần, điều kiện xóa hẳn theo `first_data_at` | backend_design §22.2 |
