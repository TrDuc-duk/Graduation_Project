# Thiết kế Frontend (cơ bản)

**Trạng thái:** bản cơ bản để bắt đầu code (04/10/2026).
**Phạm vi:** công nghệ, cấu trúc mã nguồn, route, tầng dữ liệu, i18n, quy ước hiển thị, build. Luồng màn hình chi tiết nằm ở [backend_design §12](backend_design.md#12-luồng-giao-diện-ui-flow). Thiết kế hình ảnh chi tiết (bố cục, màu, kiểu biểu đồ) để ở Phần 10.

**Ký hiệu:**
- ✅ đã chốt.
- ⏳ FE*n*: chưa chốt, tài liệu ghi theo phương án đề xuất, các phương án khác ở [mục 12](#12-các-điểm-cần-bạn-quyết-định).

---

## 1. Tóm tắt quyết định

| Chủ đề | Nội dung | Trạng thái |
|---|---|---|
| Stack | React + Vite + TypeScript, React Router, ECharts, deck.gl + MapLibre, React Three Fiber (giữ như ARCHITECHTURE) | ✅ |
| Ứng dụng | Một SPA với hai layout: người dùng (không đăng nhập) và quản trị (`/admin`) | ✅ |
| Trang chủ | "Trạm gần bạn" như Base | ✅ U1 |
| Ngôn ngữ | Tiếng Việt + English (react-i18next), mặc định tiếng Việt | ✅ U2 |
| Thời tiết | Thẻ thời tiết như Base, lấy qua backend (OpenWeatherMap) | ✅ U3 |
| Realtime | SSE từ backend (không dùng WebSocket/Socket.IO) | ✅ |
| Dữ liệu nghiệp vụ | Mức AQI, màu, khuyến nghị, thông điệp dự báo, lỗi đều lấy từ backend; frontend không tự tính AQI | ✅ |
| Quản lý dữ liệu, UI kit, nguồn bản đồ, công cụ test | Chờ chốt | ⏳ FE1–FE5 |

---

## 2. Công nghệ

| Thư viện | Dùng để | Ghi chú |
|---|---|---|
| React + TypeScript | Giao diện theo component | `strict` mode |
| Vite | Dev server, build tĩnh | Dev proxy `/api` → `http://localhost:8000` |
| React Router | Route, lazy load theo trang | `React.lazy` + `Suspense` |
| ECharts | Biểu đồ lịch sử, dự báo, heatmap độ phủ, độ chính xác model | Chỉ nạp các module dùng tới |
| MapLibre GL | Nền bản đồ | Nguồn tile: ⏳ FE4 |
| deck.gl | Cột 3D theo AQI trên bản đồ | Lazy load; có fallback 2D |
| React Three Fiber + drei | Hiệu ứng 3D trang chủ (mật độ hạt theo PM2.5) | Lazy load; tắt khi `prefers-reduced-motion` hoặc máy yếu |
| react-i18next | Chuỗi tĩnh vi/en | Chuỗi nghiệp vụ do backend trả |
| `@microsoft/fetch-event-source` | SSE có gửi header `Authorization` (kênh Admin) | Kênh công khai dùng `EventSource` |
| Quản lý dữ liệu server | Cache, retry, làm mới khi có sự kiện SSE | ⏳ FE1 |
| State toàn cục | Ngôn ngữ, phiên đăng nhập, trạng thái kết nối SSE | ⏳ FE2 |
| UI kit / styling | Bảng, form, modal, bộ chọn ngày cho Admin | ⏳ FE3 |
| Kiểm thử | Unit, component, e2e | ⏳ FE5 |

---

## 3. Cấu trúc mã nguồn

```text
frontend/
├── index.html
├── vite.config.ts             # alias @, dev proxy /api
├── src/
│   ├── main.tsx  App.tsx      # router, providers
│   ├── api/
│   │   ├── client.ts          # fetch wrapper: base URL, Accept-Language, Bearer, chuẩn hóa lỗi
│   │   ├── types.ts           # kiểu dữ liệu sinh từ OpenAPI của backend (⏳ FE1)
│   │   └── public.ts  admin.ts  auth.ts
│   ├── realtime/              # sse.ts: kết nối, thử lại, phát sự kiện tới cache
│   ├── i18n/                  # index.ts, locales/vi.json, locales/en.json
│   ├── layouts/               # UserLayout, AdminLayout
│   ├── routes/                # định nghĩa route, ProtectedRoute, RoleGuard
│   ├── pages/
│   │   ├── user/              # Home, MapView, StationDetail, Ranking, History, NotFound
│   │   └── admin/             # Login, Overview, PendingDevices, Nodes, NodeDetail, Gateways, GatewayDetail,
│   │                          # Alerts, Forecast, Data, TelemetryLogs, Users, AuditLogs, System, Config, Simulator
│   ├── components/
│   │   ├── aqi/               # AqiBadge, AqiCard, MetricCard, HealthAdvice, ForecastStrip, ConfidenceTag
│   │   ├── charts/            # SeriesChart, ForecastChart, ProfileChart, CompletenessHeatmap, AccuracyChart
│   │   ├── map/               # StationMap (deck.gl), StationMap2D (fallback), LocationPicker (Admin)
│   │   ├── three/             # ParticleScene (R3F)
│   │   └── common/            # StatusTag, EmptyState, ErrorState, StaleBanner, LanguageSwitch
│   ├── hooks/                 # useNearestStation, useStation, useForecast, useSse, useAuth
│   ├── lib/                   # format (ngày giờ, số), geolocation, featureDetect (WebGL, reduced motion)
│   └── styles/
└── tests/
```

---

## 4. Route và layout

| Route | Trang | Quyền |
|---|---|---|
| `/` | Trạm gần bạn | Công khai |
| `/map` | Bản đồ AQI | Công khai |
| `/station/:code` | Chi tiết trạm; `code` là `station_code` (vd `ST001`, P15) | Công khai |
| `/ranking` | Xếp hạng | Công khai |
| `/history` | Lịch sử dữ liệu | Công khai |
| `/admin/login` | Đăng nhập | Công khai |
| `/admin`, `/admin/devices/pending`, `/admin/nodes[/:id]` (`id` = `nodes.id`, hiển thị kèm `station_code` và `device_code`), `/admin/gateways[/:id]`, `/admin/alerts`, `/admin/forecast`, `/admin/data`, `/admin/telemetry-logs`, `/admin/logs`, `/admin/system` | Quản trị | Đã đăng nhập |
| `/admin/users`, `/admin/config` | Quản trị | Chỉ `admin` (P7) |
| `/admin/simulator` | Trạm mô phỏng | Đăng nhập (P10) |
| `*` | Không tìm thấy | Công khai |

- `ProtectedRoute`: chưa đăng nhập thì chuyển về `/admin/login?next=…`.
- `RoleGuard` ẩn mục menu và chặn route theo vai trò. Backend vẫn kiểm tra quyền; frontend chỉ ẩn cho gọn.
- Mỗi trang là một chunk riêng; deck.gl và React Three Fiber chỉ nạp ở trang cần tới.

---

## 5. Tầng dữ liệu

### 5.1. API client

- Base URL: `/api/v1` (cùng origin qua proxy). `VITE_API_BASE` chỉ dùng khi khác origin.
- Mọi request gửi `Accept-Language` theo ngôn ngữ đang chọn.
- Request Admin gửi `Authorization: Bearer <access_token>`. Nhận 401 thì gọi `POST /auth/refresh` một lần rồi gửi lại request; vẫn lỗi thì về trang đăng nhập (P12).
- Lỗi chuẩn hóa thành `{code, message}` từ `error.code` / `error.message` của backend. Giao diện quyết định theo `code` (vd `RANGE_TOO_LARGE`, `WEATHER_UNAVAILABLE`), hiển thị `message` (đã dịch).
- Không gọi trực tiếp dịch vụ ngoài nào; thời tiết cũng đi qua backend.

### 5.2. Realtime (SSE)

| Kênh | Mở ở | Cách nhận |
|---|---|---|
| `/stream/public?station_id=` | F1, F3 (một trạm); F2, F4 (không lọc) | `EventSource` |
| `/stream/admin` | Toàn bộ layout Admin (một kết nối) | `fetch-event-source` + Bearer |

- Mỗi sự kiện cập nhật hoặc đánh dấu cần tải lại dữ liệu tương ứng; bảng ánh xạ sự kiện → màn hình ở [backend_design §12.5](backend_design.md#125-sự-kiện-sse--màn-hình).
- Mất kết nối: thử lại với thời gian chờ tăng dần, hiện chấm trạng thái "Mất kết nối realtime". Kết nối lại xong thì tải lại dữ liệu của màn hình (backend không phát lại sự kiện cũ).
- Sự kiện `resync` (backend xóa hàng đợi vì client chậm, hoặc mất kết nối LISTEN): tải lại dữ liệu của màn hình như khi vừa kết nối lại ([backend_design §11.6](backend_design.md#116-realtime-sse)).
- Tab bị ẩn quá 5 phút (Page Visibility API): đóng SSE. Tab hiện lại thì mở lại và tải lại dữ liệu. Nhờ vậy nhiều tab hoặc nhiều người chung NAT ít chạm giới hạn kết nối.
- Sự kiện `auth_end` trên `/stream/admin` (JWT hết hạn hoặc phiên bị thu hồi, R32): đóng kết nối; `expired` thì refresh một lần (mục 5.3) rồi kết nối lại, `revoked` hoặc refresh thất bại thì xử lý như 401 `SESSION_REVOKED`.
- Nhận 429 `SSE_LIMIT`: không thử lại liên tục; hiện "Cập nhật realtime tạm tắt" và làm mới bằng REST mỗi 60 giây.

### 5.3. Phiên đăng nhập

- Access token chỉ giữ trong bộ nhớ, không lưu `localStorage`.
- Refresh token nằm trong cookie `HttpOnly` do backend đặt (P12); frontend không đọc được. Gọi `fetch` tới `/api/v1/auth/*` với `credentials: 'include'`.
- Tải lại trang: gọi `POST /auth/refresh` trước khi render khu Admin; thành công thì có access token mới, thất bại thì về `/admin/login`.
- Làm mới chủ động khoảng 1 phút trước khi access token hết hạn; nhiều request cùng gặp 401 chỉ gọi refresh một lần.
- **Một tab refresh tại một thời điểm (R20):** bọc lời gọi `/auth/refresh` trong `navigator.locks.request('aqi-auth-refresh', …)` (Web Locks API). Tab nào lấy được khóa thì refresh và phát access token mới cho các tab khác qua `BroadcastChannel`. Tab không lấy được khóa thì chờ token đó. Backend vẫn có khoảng ân hạn 30 giây cho trường hợp lọt qua (backend_design 11.7).
- Nhận 401 `SESSION_REVOKED` (phiên bị thu hồi, tài khoản bị khóa, đổi mật khẩu ở nơi khác): không thử refresh nữa, xóa token trong bộ nhớ, về `/admin/login` kèm thông báo "Phiên đăng nhập đã kết thúc".
- Trang "Phiên đăng nhập" trong hồ sơ người dùng: danh sách phiên (`GET /auth/sessions`) và nút đăng xuất từng phiên.

---

## 6. Màn hình

Luồng và API của từng màn hình: [backend_design §12.3–12.4](backend_design.md#123-luồng-người-dùng). Component chính:

| Màn hình | Component chính |
|---|---|
| Trạm gần bạn | `AqiCard`, `MetricCard` ×6, `HealthAdvice`, `ForecastStrip`, `WeatherCard`, `SeriesChart` (24 giờ + dự báo), danh sách trạm lân cận, `ParticleScene` |
| Bản đồ | `StationMap` / `StationMap2D`, popup trạm, chú giải AQI, nút "Vị trí của tôi" |
| Chi tiết trạm | Header trạm, `MetricCard`, tab `SeriesChart` (24 giờ/7 ngày/30 ngày), `ForecastChart` (sai số tham khảo), `ProfileChart`, `WeatherCard` |
| Xếp hạng | Bảng xếp hạng, `AqiBadge`, `StatusTag` |
| Lịch sử | Bộ chọn trạm/thông số/khoảng/độ phân giải, `SeriesChart` |
| Admin – Tổng quan | Thẻ chỉ số, danh sách "Việc cần làm", biểu đồ ingest 24 giờ, MAE theo mốc |
| Admin – Chờ duyệt | Bảng Gateway/node chờ duyệt, form duyệt với `LocationPicker` |
| Admin – Node/Gateway | Bảng + bản đồ, trang chi tiết: cảm biến, pin, vùng phủ, dữ liệu thô |
| Admin – Cảnh báo | Tab đang hoạt động / lịch sử / quy tắc |
| Admin – AI/Dự báo | Thẻ model, trạng thái theo trạm, `AccuracyChart`, so sánh dự báo vs thực tế, upload CSV |
| Admin – Dữ liệu | `CompletenessHeatmap`, xuất CSV, nhật ký telemetry |
| Admin – Hệ thống | Sức khỏe, job, sự kiện bảo mật, cấu hình |

---

## 7. Ngôn ngữ và định dạng

- Ngôn ngữ mặc định `vi`. Lựa chọn lưu trong `localStorage` (chỉ để nhớ lựa chọn, không phải dữ liệu quan trọng).
- Đổi ngôn ngữ thì gọi lại các API đang hiển thị, vì nhãn do backend trả cũng đổi.
- Ngày giờ hiển thị theo múi `Asia/Ho_Chi_Minh` bằng `Intl.DateTimeFormat` (`vi-VN` / `en-US`). Thời gian tương đối ("4 phút trước") tính từ `measured_at`.
- Số: PM, nhiệt độ, độ ẩm 1 chữ số thập phân; AQI là số nguyên. Đơn vị lấy từ trường `units` của API.
- Bổ sung chuỗi mới thì thêm cả `vi.json` và `en.json`; CI kiểm tra hai file có cùng bộ khóa.

---

## 8. Quy ước hiển thị dữ liệu

| Quy ước | Cách làm |
|---|---|
| Màu và nhãn AQI | Lấy từ `/public/aqi-scale`, không hardcode. Luôn kèm chữ (mức, con số), không chỉ dùng màu |
| Cảnh báo theo mức AQI (U4) | Thẻ AQI giờ đổi nền theo `color`/`text_color` của `level`; dải cảnh báo hiển thị `alert.title`, `alert.message` với tông `tone` (`ok`, `info`, `warning`, `critical`). Có `role="status"` (`critical` dùng `role="alert"`). SSE `hourly` đổi ngay; `level` tăng lên `usg` trở lên thì hiện toast một lần |
| AQI giờ / AQI tức thời | AQI giờ là số chính; AQI tức thời là số phụ có nhãn riêng |
| Dữ liệu thiếu | Giá trị `null` hiển thị "—"; biểu đồ để khoảng đứt (`connectNulls: false`), không nội suy |
| Dự báo | Đủ 24 mốc 3–72 giờ (P6). Nối tiếp lịch sử từ `input_hour`; nét đứt; mỗi mốc ghi "sai số trung bình khoảng ±`typical_error`" (tooltip hoặc vạch mảnh có chú thích "sai số tham khảo, không phải khoảng tin cậy"), **không** tô dải như khoảng tin cậy (khoảng hiệu chỉnh chờ P16); mốc `confidence = low` có nhãn "xu hướng" và nét mờ hơn; `issue_kind = late` hiện ghi chú "dự báo phát hành muộn". Thẻ tóm tắt nổi bật 3, 6, 12, 24 giờ. Theo `status` (backend_design 11.5, R23): `stale` → nhãn "Dự báo từ X giờ trước", chỉ vẽ các mốc tương lai; `forecast: null` → không vẽ dự báo, hiện `message` |
| Dữ liệu cũ | Banner "Mất kết nối, cập nhật lần cuối …" khi `online = false` |
| Trạng thái màn hình | Theo bảng ở [backend_design §12.2](backend_design.md#122-quy-tắc-chung-cho-mọi-màn-hình) |
| 3D | Chỉ bật khi có WebGL, không bật `prefers-reduced-motion`, không phải máy yếu; ngược lại dùng bản 2D |

---

## 9. Hiệu năng, giao diện đáp ứng, truy cập

- Giao diện đáp ứng từ 375×667 (điện thoại) đến 1280×720 trở lên, như Base.
- Lazy load theo route; deck.gl, React Three Fiber, ECharts chỉ nạp ở trang dùng tới.
- Giới hạn số hạt của React Three Fiber; dừng render khi tab ẩn.
- Dùng được bằng bàn phím cho form, bảng, menu; ảnh và icon có nhãn; độ tương phản chữ đạt mức AA.

---

## 10. Bảo mật phía frontend

- Không có bí mật trong bundle: mọi biến `VITE_*` đều công khai; API key thời tiết nằm ở backend.
- Không dùng `dangerouslySetInnerHTML` với dữ liệu từ API (tên trạm, ghi chú, payload gốc chỉ hiển thị dạng text hoặc `<pre>`).
- Không có script inline, để chạy được với CSP do Nginx đặt.
- Token theo mục 5.3.

---

## 11. Build và triển khai

- `npm run build` → `frontend/dist/`, Nginx phục vụ tĩnh; route lạ fallback về `index.html`.
- Dev: `npm run dev` (Vite), proxy `/api` tới backend local.
- Không có server Node.js ở production.

**Lộ trình** (chạy song song với backend):

| Mốc | Nội dung | Cần backend |
|---|---|---|
| FE-M0 | Khung dự án, router, layout, API client, i18n, SSE helper | M0 |
| FE-M1 | Trang người dùng: Trạm gần bạn, Chi tiết trạm, Xếp hạng, Lịch sử, thời tiết | M2 |
| FE-M2 | Dự báo trên trang người dùng; bản đồ deck.gl + fallback 2D; hiệu ứng 3D | M3 |
| FE-M3 | Admin: đăng nhập, tổng quan, chờ duyệt, node, Gateway | M4 |
| FE-M4 | Admin: cảnh báo, AI/Dự báo, dữ liệu, nhật ký, hệ thống, cấu hình, người dùng | M5, M6 |

---

## 12. Các điểm cần bạn quyết định

Tài liệu đang ghi theo phương án đề xuất (★).

| Mã | Vấn đề | Phương án | Cần trước |
|---|---|---|---|
| **FE1** | Quản lý dữ liệu từ server (cache, retry, làm mới khi có sự kiện SSE) | ★ A. TanStack Query + `fetch`, kiểu dữ liệu sinh tự động từ OpenAPI của backend (`openapi-typescript`)<br>B. Axios + lưu dữ liệu trong Zustand, như Base<br>C. Chỉ `fetch` + hook tự viết | FE-M0 |
| **FE2** | State toàn cục (ngôn ngữ, phiên, trạng thái SSE) | ★ A. Zustand, như Base<br>B. Chỉ React Context | FE-M0 |
| **FE3** | UI kit và styling | A. CSS Modules + tự xây component, như Base (nhẹ, tốn công làm bảng/form Admin)<br>★ B. Ant Design: có sẵn bảng, form, bộ chọn khoảng ngày, modal, thông báo, locale vi/en; phù hợp Admin nhiều bảng/form<br>C. Tailwind CSS + tự xây component | FE-M0 |
| **FE4** | Nguồn tile bản đồ cho MapLibre | ★ A. OpenFreeMap (vector, miễn phí, không cần key)<br>B. MapTiler (vector, cần API key, có gói miễn phí)<br>C. Tile raster OpenStreetMap như Base (phải tuân chính sách sử dụng của OSM, hình kém hơn khi nghiêng 3D) | FE-M2 |
| **FE5** | Công cụ kiểm thử | ★ A. Vitest + Testing Library (unit/component) + Playwright (e2e luồng F1, A1, A3)<br>B. Chỉ Vitest + Testing Library<br>C. Không viết test frontend | FE-M1 |

Các quyết định phía backend ảnh hưởng frontend đã chốt: P6 (đủ 24 mốc), P7 (`admin` + `operator`), P10 (trạm mô phỏng có nhãn), P12 (refresh token trong cookie). Xem [backend_design §21](backend_design.md#21-quyết-định-p1p14-và-điểm-còn-chờ).
