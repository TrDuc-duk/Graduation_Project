# Firmware và thử nghiệm IoT trong LAN

Backend dev chạy tại `http://127.0.0.1:8001`.
Gateway dùng `https://192.168.0.101:8443`; IP này phải còn được gán cho Ubuntu khi thử.
Nginx container `aqi-iot-https` chuyển tiếp HTTPS vào backend dev.
Cấu hình và chứng chỉ tự ký nằm ngoài repo: `~/.local/share/aqi-iot-lan/`.
Firmware hiện dùng `setInsecure()` nên chấp nhận chứng chỉ tự ký khi thử trong LAN.

## Chọn firmware

- `gateway-30pin`: ESP32 DOIT DevKit V1 30 chân; environment `esp32doit-devkit-v1`.
- `gateway`: bản Gateway ESP32 DevKit; environment `esp32dev`.
- `sensor-node-30pin-deepsleep`: node 30 chân với AHT10; ngủ 30 phút giữa các chu trình đo.
- `sensor-node-30pin`: node 30 chân với AHT10; FreeRTOS.
- `sensor-node`: node với DHT22; sơ đồ chân khác các bản 30 chân.

Chọn theo mạch thực tế, không nạp một biến thể chỉ vì tên gần giống.
Các bản `datn-main/firmware` được giữ nguyên để tham khảo.

## Khóa bí mật (`include/secrets.h`)

`SERVER_BASE_URL`, `PROVISION_KEY` và `GATEWAY_SECRET` (chỉ Gateway) nằm trong `include/secrets.h`; file này bị `.gitignore`, không commit.
Trước khi build lần đầu, chép mẫu rồi điền giá trị khớp `PROVISION_KEY`, `GATEWAY_SECRETS` trong `docker/.env`:

```bash
cp firmware/gateway-30pin/include/secrets.example.h firmware/gateway-30pin/include/secrets.h
```

## Kiểm tra server

```bash
curl http://127.0.0.1:8001/readyz
curl -k https://192.168.0.101:8443/readyz
docker logs --tail 30 aqi-iot-https
```

Swagger trên Ubuntu: `http://127.0.0.1:8001/api/docs`.
Từ điện thoại cùng Wi-Fi: `https://192.168.0.101:8443/readyz`.
Trình duyệt có thể cảnh báo vì chứng chỉ tự ký.

## Nạp và cấu hình Gateway

1. Cắm riêng Gateway bằng USB có truyền dữ liệu; xác định đúng loại board và cổng USB.
2. Mở đúng thư mục Gateway trong PlatformIO IDE; chọn environment chính, Build rồi Upload.
3. Mở Monitor ở 115200 baud, ghi lại Gateway ID và API Server.
4. Nếu API Server vẫn là URL cũ do NVS lưu từ trước, giữ BOOT 5 giây trong lúc firmware đang chạy để xóa cấu hình và đăng ký lại. Reset này xóa Wi-Fi và ID lưu trên Gateway.
5. Kết nối `AirQuality-GW-Setup`, mở `http://192.168.4.1`, nhập Wi-Fi cùng LAN với Ubuntu và tên Gateway.
6. Ghi nhận ID vừa cấp. Backend M1 tạo Gateway `pending`; chỉ kích hoạt đúng thiết bị đã xác định. Chưa có API Admin duyệt.

Node đã có ID và đang phát LoRa có thể giữ cấu hình hiện tại.
Nếu đăng ký lại node, firmware node cần dùng cùng URL backend; chọn `AirQuality-Node-Setup`.
Gateway phải active trước để xuất hiện trong danh sách chọn của node.

## Xác nhận dữ liệu

- Node: log `LoRa TX ... OK`.
- Gateway: nhận gói LoRa, POST telemetry thành công, response có `accepted > 0`.
- DB: có số đo mới trong `measurements`; xem thêm `trusted_at` và `qc_flags`.
- `accepted > 0` vẫn có thể là dữ liệu cách ly nếu Gateway pending.
- Với node deep-sleep, BOOT khi đang ngủ chỉ hiển thị dữ liệu cũ; không gửi mẫu mới.

Không chạy integration test đang dùng DB dev khi cần giữ dữ liệu thiết bị thật.

## Lỗi nhiệt độ/độ ẩm đứng số khi CO₂/TVOC bắt đầu có dữ liệu

Ghi nhận và xử lý ngày 16/10/2026 trên `sensor-node-30pin` (ESP32 30 chân, FreeRTOS). AHT10, CCS811 và OLED hàn cố định trên bo, dùng chung SDA GPIO21/SCL GPIO22.

### Hiện tượng và nguyên nhân

- Lượt đầu AHT10 đọc khoảng 34°C / 71% RH khi CCS811 chưa có mẫu khí. Các lượt sau CO₂/TVOC có số thì độ ẩm về 0%, nhiệt độ lặp nguyên giá trị cũ. Dữ liệu sai đã xuất hiện trong frame đọc tại node, trước LoRa và backend.
- AHT10 không duy trì phép đo đúng trên cấu hình bus dùng chung hiện tại, nhưng firmware cũ vẫn chấp nhận frame có nhiệt độ cũ/độ ẩm 0. Tăng thời gian chờ lên 120 ms riêng lẻ vẫn tái hiện lỗi. Tài liệu AHT10 có cảnh báo không dùng chung bus với thiết bị I²C khác; chưa tách vật lý nên chưa xác định riêng CCS811 hay OLED gây ảnh hưởng.
- Bộ lọc CCS811 cũ loại mọi TVOC trên 1.187 ppb rồi trả khí về 0, dù các mẫu này có thể hợp lệ. Độ ẩm sai còn được đưa vào bù trừ CCS811, có thể làm kết quả khí lệch thêm. Hiện tượng hai nhóm thông số thay nhau đúng không phải quan hệ ngược nhau giữa các đại lượng môi trường.

### Cách sửa đang áp dụng

1. Phục hồi riêng AHT10 trước mỗi lượt đo: soft reset, khởi tạo lại, chờ 120 ms sau lệnh đo và kiểm tra ACK, đủ byte, trạng thái busy/hiệu chuẩn. Các lần chờ/thử lại có giới hạn; lỗi đọc trả sentinel thay vì lấy số đo cũ.
2. Giữ CCS811 chạy liên tục để không khởi động lại quá trình làm nóng; OLED giữ cùng tốc độ bus 10 kHz, không tự chuyển sang 400/100 kHz.
3. CCS811 kiểm tra DATA_READY, độ dài frame và trạng thái lỗi. Chưa có mẫu gửi 0; lỗi gửi sentinel 65535. TVOC bằng 0 vẫn hợp lệ khi eCO₂ hợp lệ.
4. Đồng bộ dải đầu ra ở firmware và backend theo datasheet ams v1-06: eCO₂ 400–29.206 ppm, TVOC 0–32.768 ppb. Migration `0004_ccs811_range` đổi cột TVOC từ `smallint` sang `integer` để chứa được 32768, giữ dữ liệu cũ.

### Kết quả kiểm chứng và giới hạn

- UART: 12 chu kỳ trong 180 giây, không có lỗi AHT10; nhiệt độ 33,9–34,0°C, độ ẩm 70,7–71,4%, CO₂/TVOC đồng thời có số và thay đổi.
- Backend: 81 test đạt trên DB riêng; migration dev giữ đủ 94 số đo cũ. Đây không phải kết quả kiểm tra lại toàn tuyến LoRa → Gateway → backend sau sửa, vì Gateway đã rút USB trong lúc kiểm chứng.
- Phục hồi AHT10 là biện pháp bằng firmware cho bo hiện tại; phép thử 3 phút chưa chứng minh độ ổn định lâu dài khi dùng chung bus. Khi sửa phần cứng, hướng xử lý là tách AHT10 sang bus riêng.
- CCS811 cần conditioning khoảng 20 phút sau khi bắt đầu đo. eCO₂ là giá trị tương đương suy ra từ cảm biến khí, không phải phép đo CO₂ trực tiếp.

Xem [ghi chép chẩn đoán và lệnh kiểm thử](sensor-node-30pin/DIAGNOSTICS.md).
Nguồn: [AHT10 Technical Manual, trang 8–10](https://arduino.ua/files/AOSONG_AHT10_EN.PDF), [ams CCS811 datasheet v1-06](https://cdn.sparkfun.com/assets/2/c/c/6/5/CN04-2019_attachment_CCS811_Datasheet_v1-06.pdf).
