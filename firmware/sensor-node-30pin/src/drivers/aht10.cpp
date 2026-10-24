#include "aht10.h"
#include <Arduino.h>
#include <math.h>
#include <Wire.h>
#include "config.h"
#include "common/debug.h"
#include "common/packet.h"

// =============================================================================
//  AHT10 DRIVER IMPLEMENTATION
//  Dải đo: Nhiệt độ -40~85°C (±0.3°C), Độ ẩm 0~100% (±2%)
//  Giao tiếp: I2C (chung bus Wire, SDA=21, SCL=22)
//  Thay thế DHT22 trên board 30 chân
// =============================================================================

// Gửi lệnh và xác nhận ACK; không thay đổi bus của CCS811/OLED.
static bool aht10_command(const uint8_t* command, size_t size) {
    Wire.beginTransmission(AHT10_ADDR);
    Wire.write(command, size);
    return Wire.endTransmission() == 0;
}

// Reset riêng AHT10, hiệu chuẩn lại và chờ sẵn sàng với số lần thử hữu hạn.
static bool aht10_reset() {
    const uint8_t reset[] = {0xBA};
    const uint8_t calibrate[] = {0xE1, 0x08, 0x00};
    if (!aht10_command(reset, sizeof(reset))) return false;
    delay(30);
    if (!aht10_command(calibrate, sizeof(calibrate))) return false;
    delay(10);
    for (int poll = 0; poll < 10; ++poll) {
        if (Wire.requestFrom((uint8_t)AHT10_ADDR, (uint8_t)1) != 1) return false;
        uint8_t status = Wire.read();
        if (!(status & 0x80)) return (status & 0x68) == 0x08;
        delay(10);
    }
    return false;
}

bool aht10_init() {
    if (!aht10_reset()) {
        LOG_MSG("AHT10", "THẤT BẠI! Không tìm thấy sensor hoặc chưa sẵn sàng.");
        return false;
    }
    LOG_MSG("AHT10", "Khởi tạo... OK!");
    return true;
}

bool aht10_read(int16_t* temperature, uint16_t* humidity) {
    *temperature = SENSOR_ERROR_I16;
    *humidity    = SENSOR_ERROR_U16;

    for (int attempt = 1; attempt <= SENSOR_READ_RETRIES; attempt++) {
        // Bo hiện hàn AHT10 chung I2C: phục hồi riêng nó sau lưu lượng OLED/CCS811.
        // Không reset CCS811 để giữ quá trình làm nóng cảm biến khí.
        if (!aht10_reset()) {
            LOG_INFO("AHT10", "Phục hồi thất bại (%d/%d)", attempt, SENSOR_READ_RETRIES);
            delay(100);
            continue;
        }
        // Chờ đủ thời gian chuyển đổi trước khi đọc toàn bộ frame.
        // Theo datasheet AHT10, thời gian chờ sau trigger phải lớn hơn 75 ms.
        const uint8_t command[] = {0xAC, 0x33, 0x00};
        bool readOK = aht10_command(command, sizeof(command));
        uint8_t data[6]{};
        if (readOK) {
            delay(120);
            for (int poll = 0; poll < 5; ++poll) {
                readOK = Wire.requestFrom((uint8_t)AHT10_ADDR, (uint8_t)6) == 6;
                if (!readOK) break;
                for (uint8_t &byte : data) byte = Wire.read();
                if (!(data[0] & 0x80)) break;
                delay(20);
            }
            readOK = readOK && !(data[0] & 0x80) && (data[0] & 0x08);
        }

        if (readOK) {
            LOG_INFO("AHT10", "Frame: %02X %02X %02X %02X %02X %02X",
                     data[0], data[1], data[2], data[3], data[4], data[5]);
            uint32_t rawH = ((uint32_t)data[1] << 12) |
                            ((uint32_t)data[2] << 4) | (data[3] >> 4);
            uint32_t rawT = ((uint32_t)(data[3] & 0x0F) << 16) |
                            ((uint32_t)data[4] << 8) | data[5];
            float t = rawT * (200.0f / 1048576.0f) - 50.0f;
            float h = rawH * (100.0f / 1048576.0f);
            if (t >= -40.0f && t <= 85.0f && h <= 100.0f) {
                *temperature = (int16_t)lroundf(t * 10.0f);
                *humidity = (uint16_t)lroundf(h * 10.0f);
                LOG_INFO("AHT10", "Nhiệt độ: %.1f°C | Độ ẩm: %.1f%%", t, h);
                return true;
            }
            LOG_INFO("AHT10", "Giá trị không hợp lệ: T=%.1f H=%.1f", t, h);
        } else {
            LOG_INFO("AHT10", "Đọc I2C/trạng thái thất bại (%d/%d)", attempt, SENSOR_READ_RETRIES);
        }

        if (attempt < SENSOR_READ_RETRIES) {
            // Reset riêng AHT10 trong lúc sensorTask đang giữ mutex I2C.
            delay(100);
            delay(500);
        }
    }

    LOG_MSG("AHT10", "THẤT BẠI! Trả về SENSOR_ERROR");
    return false;
}
