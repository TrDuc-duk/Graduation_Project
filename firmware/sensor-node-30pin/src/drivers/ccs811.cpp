#include "ccs811.h"
#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_CCS811.h>
#include "config.h"
#include "common/debug.h"
#include "common/packet.h"

// =============================================================================
//  CCS811 DRIVER IMPLEMENTATION (30-pin board)
//  Dải đầu ra theo ams v1-06: eCO2 400-29206 ppm, eTVOC 0-32768 ppb
//  Lưu ý: Cần warm-up ~20 phút để dữ liệu chính xác
//
//  Board 30 chân: thêm CCS811_WAK_PIN và CCS811_ADD_PIN
//  Chung bus I2C với OLED → cần bus recovery khi lỗi
// =============================================================================

static Adafruit_CCS811 ccs;
static unsigned long ccs811StartTime = 0;

// Số lần retry riêng cho CCS811 (cao hơn SENSOR_READ_RETRIES vì bus bị nhiễu OLED)
#define CCS811_MAX_RETRIES 5

/**
 * Phục hồi bus I2C khi bị kẹt (stuck SDA LOW)
 * Toggle SCL thủ công để giải phóng slave đang giữ bus
 */
static void i2c_busRecovery() {
    Wire.end();
    pinMode(CCS811_SDA_PIN, INPUT_PULLUP);
    pinMode(CCS811_SCL_PIN, OUTPUT);

    // Toggle SCL 9 lần để unstick slave
    for (int i = 0; i < 9; i++) {
        digitalWrite(CCS811_SCL_PIN, LOW);
        delayMicroseconds(100);
        digitalWrite(CCS811_SCL_PIN, HIGH);
        delayMicroseconds(100);
    }

    // Khởi tạo lại Wire
    Wire.begin(CCS811_SDA_PIN, CCS811_SCL_PIN);
    Wire.setClock(I2C_CLOCK_HZ);
    Wire.setTimeOut(3000);
    delay(50);
    LOG_MSG("CCS811", "Bus I2C recovery done.");
}

// Đọc đúng số byte và kiểm tra ACK trước khi giải mã; thư viện không trả lỗi I2C.
static bool ccs811_readRegister(uint8_t reg, uint8_t* data, uint8_t size) {
    Wire.beginTransmission(CCS811_ADDR);
    Wire.write(reg);
    if (Wire.endTransmission() != 0) return false;
    if (Wire.requestFrom((uint8_t)CCS811_ADDR, size) != size) return false;
    for (uint8_t i = 0; i < size; ++i) data[i] = Wire.read();
    return true;
}

bool ccs811_init() {
    // Khởi tạo chân điều khiển CCS811 (theo AirMonitorModule)
    pinMode(CCS811_WAK_PIN, OUTPUT);
    pinMode(CCS811_ADD_PIN, OUTPUT);
    digitalWrite(CCS811_WAK_PIN, LOW);   // Wake sensor (active LOW)
    digitalWrite(CCS811_ADD_PIN, LOW);   // Address = 0x5A
    delay(200);  // Đợi CCS811 boot sau khi wake (datasheet: ~70ms app start)

    // Wire đã được khởi tạo trong initAllHardware()

    if (!ccs.begin(CCS811_ADDR)) {
        LOG_MSG("CCS811", "THẤT BẠI! Không tìm thấy sensor.");
        return false;
    }

    // Không chờ vô hạn ở đây: ccs811_read() sẽ kiểm tra DATA_READY có giới hạn.
    // Drive mode 1: đo mỗi 1 giây
    ccs.setDriveMode(CCS811_DRIVE_MODE_1SEC);

    ccs811StartTime = millis();
    LOG_MSG("CCS811", "Khởi tạo... OK!");
    LOG_MSG("CCS811", "Cần warm-up 20 phút để dữ liệu chính xác.");
    return true;
}

void ccs811_setEnvData(int16_t temperature, uint16_t humidity) {
    // Chuyển đổi lại từ ×10 sang float
    float tempC = temperature / 10.0f;
    float humPct = humidity / 10.0f;

    uint16_t encodedH = (uint16_t)(humPct * 512.0f + 0.5f);
    uint16_t encodedT = (uint16_t)((tempC + 25.0f) * 512.0f + 0.5f);
    const uint8_t data[] = {0x05, (uint8_t)(encodedH >> 8), (uint8_t)encodedH,
                          (uint8_t)(encodedT >> 8), (uint8_t)encodedT};
    Wire.beginTransmission(CCS811_ADDR);
    Wire.write(data, sizeof(data));
    if (Wire.endTransmission() != 0) {
        LOG_MSG("CCS811", "Ghi ENV thất bại, cảm biến giữ mức bù trừ trước đó.");
        return;
    }
    LOG_INFO("CCS811", "ENV compensation: T=%.1f°C, H=%.1f%%", tempC, humPct);
}

bool ccs811_read(uint16_t* co2, uint16_t* tvoc) {
    *co2 = SENSOR_ERROR_U16;
    *tvoc = SENSOR_ERROR_U16;
    int transportErrors = 0;
    bool onlyNotReady = true;

    for (int attempt = 1; attempt <= CCS811_MAX_RETRIES; ++attempt) {
        uint8_t status = 0;
        uint8_t data[8]{};
        bool transportOK = ccs811_readRegister(0x00, &status, 1);
        if (transportOK && (status & 0x91) == 0x90 && (status & 0x08)) {
            transportOK = ccs811_readRegister(0x02, data, sizeof(data));
            if (transportOK) {
                uint16_t measuredCo2 = ((uint16_t)data[0] << 8) | data[1];
                uint16_t measuredTvoc = ((uint16_t)data[2] << 8) | data[3];
                if ((data[4] & 0x91) == 0x90 && data[5] == 0) {
                    if (measuredCo2 >= 400 && measuredCo2 <= 29206 && measuredTvoc <= 32768) {
                        *co2 = measuredCo2;
                        *tvoc = measuredTvoc;
                        LOG_INFO("CCS811", "CO2: %d ppm | TVOC: %d ppb", *co2, *tvoc);
                        if (!ccs811_isWarmedUp())
                            LOG_MSG("CCS811", "Chưa warm-up đủ 20 phút, dữ liệu có thể chưa chính xác.");
                        return true;
                    }
                    if (measuredCo2 != 0 || measuredTvoc != 0) onlyNotReady = false;
                    LOG_INFO("CCS811", "Mẫu chưa hợp lệ: CO2=%d TVOC=%d", measuredCo2, measuredTvoc);
                } else {
                    onlyNotReady = false;
                    LOG_INFO("CCS811", "Lỗi cảm biến: status=%02X error=%02X", data[4], data[5]);
                }
            }
        } else if (transportOK && (status & 0x91) != 0x90) {
            onlyNotReady = false;
            LOG_INFO("CCS811", "Trạng thái lỗi: %02X", status);
        }
        if (!transportOK) {
            onlyNotReady = false;
            if (++transportErrors >= 3) {
                i2c_busRecovery();
                transportErrors = 0;
            }
            LOG_INFO("CCS811", "Đọc I2C thiếu byte/NACK (%d/%d)", attempt, CCS811_MAX_RETRIES);
        } else {
            transportErrors = 0;
        }
        delay(1000);
    }

    // 0 chỉ dành cho chưa có mẫu; lỗi giao tiếp/cảm biến dùng sentinel 65535.
    if (onlyNotReady) {
        *co2 = 0;
        *tvoc = 0;
        LOG_MSG("CCS811", "Chưa có dữ liệu sẵn sàng.");
    } else {
        LOG_MSG("CCS811", "THẤT BẠI! Trả về SENSOR_ERROR.");
    }
    return false;
}

bool ccs811_isWarmedUp() {
    return (millis() - ccs811StartTime) >= CCS811_WARMUP_MS;
}

