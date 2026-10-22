# Báo cáo tiến độ tuần 6

**Đề tài:** Hệ thống giám sát chất lượng không khí và dự báo AQI sử dụng IoT và học máy.  
**Ngày cập nhật:** 16/10/2026.

## 1. Mục tiêu

- Triển khai luồng tiếp nhận dữ liệu từ node cảm biến qua LoRa và Gateway về backend.
- Xây dựng dashboard theo dõi số đo và trạng thái thiết bị.
- Kiểm tra lỗi cảm biến trên phần cứng thực tế và chuẩn bị môi trường chạy bằng Docker.

## 2. Công việc đã triển khai

### Backend và cơ sở dữ liệu

- Xây dựng backend FastAPI, cấu hình ứng dụng, kết nối cơ sở dữ liệu, xử lý lỗi và các job nền.
- Triển khai đăng ký thiết bị, tiếp nhận telemetry, chuẩn hóa số đo, kiểm tra chất lượng dữ liệu và xử lý gói trùng.
- Lưu dữ liệu trên PostgreSQL kết hợp TimescaleDB và PostGIS; quản lý schema bằng Alembic.
- Bổ sung API dev chỉ đọc để lấy danh sách node và lịch sử số đo trong 1, 6 hoặc 24 giờ, kèm trạng thái thiết bị, độ mới dữ liệu, đơn vị và cờ chất lượng.
- Cung cấp `/healthz`, `/readyz` và Swagger ở `/api/docs` trong môi trường dev.
- Migration `0004_ccs811_range` chuyển cột TVOC sang `integer` để lưu được giá trị 32768 ppb.

### Frontend

- Xây dựng dashboard bằng React, TypeScript và Vite; dùng ECharts để biểu diễn dữ liệu.
- Hiển thị PM2.5, PM10, eCO₂, TVOC, nhiệt độ, độ ẩm và pin; hỗ trợ chọn node và khoảng thời gian.
- Tự cập nhật mỗi 10 giây, hiển thị trạng thái tải, mất kết nối, chưa có dữ liệu và dữ liệu cũ.
- Hiển thị thông tin chất lượng dữ liệu và trạng thái thiết bị chưa được duyệt để hỗ trợ kiểm tra trong môi trường dev.

### Firmware và kiểm tra cảm biến

- Chuẩn bị các biến thể firmware ESP32 Gateway và node, gồm bản 30 chân và bản deep-sleep.
- Ghi nhận lỗi AHT10 đứng nhiệt độ/độ ẩm khi dùng chung bus I²C với CCS811 và OLED.
- Bổ sung phục hồi AHT10 trước lượt đo, kiểm tra trạng thái và độ dài dữ liệu, giới hạn thời gian chờ và số lần thử lại.
- Giữ CCS811 hoạt động liên tục, phân biệt chưa có mẫu với lỗi đọc và đồng bộ dải dữ liệu giữa firmware với backend.
- Bổ sung tài liệu cấu hình, kiểm tra đường truyền và chẩn đoán trong [README firmware](../firmware/README.md).

### Docker

- Sử dụng Compose dev cho database, backend và frontend; frontend được build rồi phục vụ qua Nginx.
- Chuyển tiếp `/api/` từ frontend tới backend trong mạng Docker, giúp trình duyệt gọi API cùng origin.
- Bổ sung healthcheck cho backend và frontend, đồng thời giữ database trên volume riêng.
- Tạo lại container database theo đường dẫn workspace hiện tại để khắc phục lỗi bind mount còn trỏ tới vị trí dự án cũ.

## 3. Phân tích lỗi cảm biến và nguyên nhân

### 3.1. Hiện tượng quan sát được

Lỗi được ghi nhận trên bản **`sensor-node-30pin` dùng FreeRTOS**, với AHT10 đo nhiệt độ/độ ẩm, CCS811 đo khí và OLED hàn chung hai đường SDA GPIO21/SCL GPIO22. Lượt đầu AHT10 đọc khoảng 34°C và 71% RH; những lượt tiếp theo, khi eCO₂/TVOC bắt đầu có số, phần nhiệt độ trong frame AHT10 lặp lại giá trị cũ và phần độ ẩm về 0%.

Điểm quan trọng là frame sai đã được quan sát ở UART của node, trước khi đóng gói và truyền LoRa. Vì vậy, lỗi số đo này phát sinh ở khâu cảm biến/đọc cảm biến; dữ liệu sai trên dashboard là hệ quả của dữ liệu đầu vào sai. Việc hai nhóm thông số thay nhau có vẻ đúng không đủ để kết luận chúng có quan hệ ngược nhau về mặt môi trường.

### 3.2. Nguyên nhân nghi ngờ chính: AHT10 không ổn định trên bus dùng chung

Bus I²C là cặp dây giao tiếp được cả ba thiết bị sử dụng. Thiết kế hiện tại đặt AHT10 trên cùng bus với CCS811 và OLED, trong khi **tài liệu AHT10 yêu cầu bus chỉ nối một AHT10 và không nối thiết bị I²C khác**. Đây là điểm không phù hợp giữa thiết kế bo và hướng dẫn của nhà sản xuất. Xem ghi chú sơ đồ ứng dụng ở [AHT10 Technical Manual, trang 8](https://arduino.ua/files/AOSONG_AHT10_EN.PDF#page=8).

Từ hiện tượng frame AHT10 bất thường và kết quả phục hồi sau khi reset riêng cảm biến, hướng chẩn đoán hiện tại là **trạng thái đo/giao tiếp AHT10 bị ảnh hưởng trong cấu hình bus chung**. Đây là suy luận từ thử nghiệm, chưa phải kết luận đã xác định được cơ chế điện cụ thể. Chưa có phép thử tách lần lượt CCS811 và OLED, hoặc đo dạng sóng SDA/SCL, nên chưa thể khẳng định riêng CCS811, riêng OLED, nhiễu tín hiệu hay thay đổi tốc độ bus là tác nhân trực tiếp.

Các địa chỉ cấu hình khác nhau: AHT10 `0x38`, CCS811 `0x5A`; chưa có bằng chứng lỗi do trùng hai địa chỉ này. Mutex trong FreeRTOS giúp các tác vụ không chen ngang giao dịch I²C của nhau, nhưng không khắc phục được mọi hạn chế của cảm biến hoặc vấn đề điện trên đường dây. Vì vậy, chỉ thêm mutex chưa đủ để chứng minh bus đã ổn định.

### 3.3. Vì sao firmware vẫn đưa số đo sai lên hệ thống?

Theo ghi chép chẩn đoán, đường đọc cũ vẫn chấp nhận frame có nhiệt độ lặp và độ ẩm 0. Hai giá trị này vẫn có thể nằm trong dải số hợp lệ, nên kiểm tra khoảng giá trị đơn thuần không phát hiện được việc phép đo không cập nhật đúng. Riêng giá trị 0% RH không phải bằng chứng lỗi trong mọi trường hợp; ở lần thử này, kết luận dựa trên diễn biến từ khoảng 71% xuống 0% và frame lặp bất thường.

Việc chỉ tăng thời gian chờ sau lệnh đo lên 120 ms đã được thử nhưng lỗi vẫn tái hiện. Điều này cho thấy giả thuyết “đọc quá sớm” chưa giải thích đầy đủ hiện tượng. Bản sửa phải kết hợp phục hồi cảm biến và kiểm tra giao tiếp/trạng thái, thay vì chỉ kéo dài thời gian chờ.

Nhiệt độ và độ ẩm còn được gửi cho CCS811 để bù trừ kết quả khí qua `ENV_DATA`. Nếu AHT10 trả số sai nhưng vẫn được coi là hợp lệ, dữ liệu bù trừ cũng sai và có thể làm kết quả khí lệch thêm. Chưa có phép đo đối chứng để định lượng mức lệch này. Cơ chế bù trừ được mô tả trong [CCS811 datasheet v1-06, trang 12](https://cdn.sparkfun.com/assets/2/c/c/6/5/CN04-2019_attachment_CCS811_Datasheet_v1-06.pdf#page=12).

### 3.4. Vấn đề riêng ở CCS811: loại nhầm mẫu và nhập nhằng giá trị 0

Ngoài lỗi AHT10, bộ lọc CCS811 cũ loại mẫu khi eCO₂ vượt 8192 ppm hoặc TVOC vượt 1187 ppb, rồi có thể đưa kết quả về 0. Trong khi đó, datasheet v1-06 công bố dải đầu ra eCO₂ 400–29206 ppm và eTVOC 0–32768 ppb. Như vậy, một số mẫu trong dải đầu ra của cảm biến đã bị phần mềm loại nhầm. Đây là lỗi xử lý dữ liệu độc lập, không chứng minh CCS811 làm hỏng phép đo AHT10. Các dải này là dải đầu ra, không phải ngưỡng đánh giá an toàn không khí. Nguồn: [CCS811 datasheet v1-06, trang 12](https://cdn.sparkfun.com/assets/2/c/c/6/5/CN04-2019_attachment_CCS811_Datasheet_v1-06.pdf#page=12).

Quy ước cũ cũng dễ làm lẫn “chưa có mẫu”, “đọc lỗi” và “TVOC thực sự bằng 0”. Bản sửa tách các trường hợp: đường đọc CCS811 trả cặp 0 khi chưa có mẫu, sentinel `65535` khi đọc lỗi; TVOC bằng 0 vẫn được chấp nhận nếu eCO₂ hợp lệ. Backend chuyển mẫu lỗi/chưa sẵn sàng thành `null` và gắn cờ tương ứng, tránh hiển thị như số đo khí bằng 0.

CCS811 còn cần conditioning khoảng 20 phút sau khi bắt đầu chế độ đo. Có số trong giai đoạn này chưa đồng nghĩa kết quả đã ổn định; khoảng conditioning cũng không giải thích được frame AHT10 sai. eCO₂ là giá trị CO₂ tương đương do thuật toán suy ra từ cảm biến khí. Xem [CCS811 datasheet v1-06, mục Conditioning Period và eCO₂](https://cdn.sparkfun.com/assets/2/c/c/6/5/CN04-2019_attachment_CCS811_Datasheet_v1-06.pdf#page=12).

### 3.5. Cách sửa và tác dụng

| Thay đổi đang áp dụng | Mục đích |
|---|---|
| Soft reset riêng AHT10, khởi tạo lại trước mỗi lượt đo | Phục hồi trạng thái cảm biến trên bo hiện tại |
| Kiểm tra ACK, đủ 6 byte, hết busy và đã hiệu chuẩn; chờ 120 ms sau trigger | Loại lỗi giao tiếp/trạng thái trước khi giải mã |
| Giới hạn số lần thử và thời gian chờ; lỗi trả sentinel | Tránh treo tác vụ và tránh phát số cũ như một phép đo mới |
| Giữ tốc độ bus 10 kHz, cấu hình OLED không tự đổi sang 400/100 kHz; giữ mutex I²C | Thống nhất cấu hình bus và tuần tự hóa truy cập |
| Giữ CCS811 chạy liên tục; kiểm tra DATA_READY, trạng thái lỗi và đủ byte | Hạn chế gián đoạn quá trình ổn định cảm biến và phân biệt tình trạng đọc |
| Đồng bộ dải khí ở firmware/backend; đổi TVOC sang `integer` | Nhận đủ dải đầu ra và lưu được 32768, vượt giới hạn `smallint` có dấu 32767 |

Reset AHT10 là biện pháp phục hồi bằng firmware, chưa thay thế việc sửa thiết kế bus. Kiểm tra trạng thái và dải đo cũng chưa bảo đảm phát hiện mọi frame sai nhưng vẫn có hình thức hợp lệ. Phạm vi bản sửa được đối chiếu ở đây là `sensor-node-30pin`; chưa suy rộng kết quả sang các biến thể firmware khác.

### 3.6. Kết luận và phép thử còn cần thực hiện

**Đã xác nhận:** frame AHT10 sai ngay tại node; tăng thời gian chờ riêng lẻ không hết lỗi; bản phục hồi hiện tại cho kết quả tốt trong thử nghiệm UART ngắn. **Chưa xác nhận:** thiết bị nào trên bus gây ảnh hưởng trực tiếp, cơ chế điện cụ thể và độ ổn định lâu dài.

Bước tiếp theo là tách AHT10 sang bus riêng, thử từng tổ hợp thiết bị với cùng điều kiện và theo dõi dài hạn. Nếu lỗi còn xuất hiện, cần kiểm tra nguồn, pull-up và dạng sóng SDA/SCL. Sau đó chạy lại toàn tuyến node → LoRa → Gateway → backend → dashboard để xác nhận số đo được giữ đúng qua các bước.

Bằng chứng nội bộ: [ghi chép chẩn đoán](../firmware/sensor-node-30pin/DIAGNOSTICS.md), [driver AHT10](../firmware/sensor-node-30pin/src/drivers/aht10.cpp), [driver CCS811](../firmware/sensor-node-30pin/src/drivers/ccs811.cpp), [tác vụ đọc cảm biến](../firmware/sensor-node-30pin/src/tasks/sensor_task.cpp) và [chuẩn hóa dữ liệu backend](../backend/app/modules/ingest/normalize.py).

## 4. Kết quả và giới hạn kiểm chứng

Theo ghi nhận ngày 16/10/2026 trong tài liệu firmware:

- UART chạy 12 chu kỳ trong 180 giây không có lỗi AHT10; nhiệt độ 33,9–34,0°C, độ ẩm 70,7–71,4%; eCO₂/TVOC đồng thời có dữ liệu và thay đổi.
- Backend có 81 test đạt trên cơ sở dữ liệu riêng; migration dev giữ đủ 94 số đo cũ ở lần kiểm tra được ghi nhận.

Các số liệu trên là kết quả kiểm chứng đã ghi trong tài liệu dự án, không phải số liệu của một lần chạy lại test trong lúc lập báo cáo. Thử nghiệm UART ngắn chưa chứng minh độ ổn định lâu dài của bus I²C. Sau sửa firmware vẫn cần kiểm tra lại toàn tuyến node → LoRa → Gateway → backend → dashboard.

Dashboard hiện phục vụ kiểm tra dữ liệu cảm biến qua API dev. Chức năng dự báo trực tuyến, API quản trị đầy đủ và SSE chưa được xác nhận hoàn tất trong phạm vi báo cáo này.

Kiểm tra Docker khi lập báo cáo: cả ba service `db`, `api`, `frontend` đều `healthy`; frontend, Swagger và API danh sách node qua Nginx trả HTTP 200. `/readyz` xác nhận kết nối DB cùng hai extension hoạt động, model vẫn `not_loaded`. Alembic đang ở `0004_ccs811_range (head)`; build TypeScript/Vite và kiểm tra cấu hình Nginx đều thành công.

## 5. Kế hoạch tuần tiếp theo

1. Chạy thử toàn tuyến với Gateway và node thực, đối chiếu số đo UART, telemetry, database và dashboard.
2. Theo dõi AHT10 trong thời gian dài; xem xét tách bus I²C khi điều chỉnh phần cứng.
3. Tiếp tục hoàn thiện quản trị thiết bị và luồng duyệt thiết bị.
4. Tích hợp pipeline dự báo AQI vào backend, kiểm tra điều kiện dữ liệu đầu vào và hiển thị kết quả dự báo.
5. Chạy kiểm thử hồi quy trên database riêng và cập nhật bằng chứng kiểm thử.

## 6. Chạy môi trường local

Từ thư mục gốc dự án, sau khi cấu hình `docker/.env` theo file mẫu:

```bash
docker compose -f docker/docker-compose.dev.yml up -d --build --wait db
docker compose -f docker/docker-compose.dev.yml build api
docker compose -f docker/docker-compose.dev.yml run --rm api alembic upgrade head
docker compose -f docker/docker-compose.dev.yml up -d --build --wait api frontend
docker compose -f docker/docker-compose.dev.yml ps
```

- Frontend mặc định: <http://localhost:5173>.
- Backend trên máy hiện tại (`API_PORT=8001`): <http://localhost:8001>; Swagger: <http://localhost:8001/api/docs>.
- Compose mặc định dùng cổng backend 8000 nếu chưa đặt `API_PORT`; dùng 8001 khi cổng 8000 đã bị ứng dụng khác chiếm.
- Xem thêm [hướng dẫn Docker](../docker/README.md). Không đưa `docker/.env` hoặc dữ liệu volume vào Git.
