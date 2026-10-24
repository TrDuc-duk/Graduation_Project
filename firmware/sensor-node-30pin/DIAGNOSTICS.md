# AHT10 đứng số khi CCS811 bắt đầu có dữ liệu

Bo đang thử là node ESP32 30 chân dùng FreeRTOS, AHT10/CCS811/OLED hàn chung SDA21/SCL22.

Trước sửa: lượt đầu khoảng 34°C/71% RH, các lượt sau frame AHT10 lặp nguyên phần nhiệt độ và phần độ ẩm bằng 0. Tăng thời gian chờ sau trigger lên 120 ms vẫn tái hiện. Dữ liệu sai có ngay ở UART node, trước LoRa và backend.

Bản hiện tại phục hồi riêng AHT10 (soft reset, lệnh khởi tạo AHT10 0xE1, kiểm tra trạng thái với số lần thử hữu hạn) trước mỗi lượt đo; chờ 120 ms sau trigger và chỉ giải mã frame đủ byte, hết busy và đã hiệu chuẩn. Không reset CCS811 mỗi chu kỳ. OLED giữ cùng tốc độ bus 10 kHz thay vì tự đổi sang 400/100 kHz. Lỗi đọc trả sentinel, không lấy lại số đo cũ.

CCS811 kiểm tra ACK, độ dài frame, DATA_READY và trạng thái lỗi. Chỉ gửi 0 khi chưa có mẫu, gửi 65535 khi lỗi; TVOC thực sự bằng 0 vẫn hợp lệ nếu eCO2 hợp lệ. Dải đầu ra dùng eCO2 400–29206 ppm, TVOC 0–32768 ppb theo datasheet ams v1-06. Backend áp dụng cùng dải, migration `0004_ccs811_range` đổi cột TVOC sang integer vì smallint không chứa được 32768. Migration giữ số đo và phục hồi trạng thái nén của chunk.

Theo dõi UART sau nạp trong 180 giây: 12 chu kỳ, không có lỗi AHT10; nhiệt độ 33,9–34,0°C và độ ẩm 70,7–71,4%, trong khi eCO2/TVOC đồng thời có số. Backend đạt 81 test trên DB riêng; migration dev giữ đủ 94 số đo cũ. Gateway đang rút USB nên chưa kiểm tra lại toàn tuyến LoRa → Gateway → backend sau bản sửa này. Đây là biện pháp phục hồi bằng firmware cho bo hiện tại, chưa chứng minh việc dùng chung bus sẽ ổn định lâu dài. Chưa có phép thử tách vật lý để xác định CCS811 hay OLED gây nhiễu AHT10. Với lần sửa phần cứng, nên tách AHT10 sang bus riêng: tài liệu AHT10 cảnh báo không chia sẻ bus với thiết bị khác.

CCS811 cần thời gian conditioning khoảng 20 phút sau khi bắt đầu đo; eCO2 là giá trị tương đương suy ra từ cảm biến khí, không phải phép đo CO2 trực tiếp.

## Kiểm chứng không dùng DB thiết bị thật

```bash
python3 firmware/sensor-node-30pin/test/host/run.py
pio run -d firmware/sensor-node-30pin -e esp32doit-devkit-v1
```

Test backend có fixture xóa dữ liệu: chỉ chạy integration/schema trên DB riêng có tên kết thúc `_test`. Không trỏ test vào DB `aqi` đang nhận số đo thật.

## Nguồn

- [AHT10 Technical Manual, trang 8–10](https://arduino.ua/files/AOSONG_AHT10_EN.PDF): hạn chế bus và giao thức trigger/chờ/đọc.
- [ams CCS811 datasheet v1-06](https://cdn.sparkfun.com/assets/2/c/c/6/5/CN04-2019_attachment_CCS811_Datasheet_v1-06.pdf): dải đầu ra và conditioning.
- [Adafruit AHTX0](https://github.com/adafruit/Adafruit_AHTX0): tham khảo cách giải mã dữ liệu.
