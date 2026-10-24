#include "aht10.h"
#include <Arduino.h>
#include <Adafruit_AHTX0.h>
#include "config.h"
#include "common/debug.h"
#include "common/packet.h"

// =============================================================================
//  AHT10 DRIVER IMPLEMENTATION
//  Dải đo: Nhiệt độ -40~85°C (±0.3°C), Độ ẩm 0~100% (±2%)
//  Giao tiếp: I2C (chung bus Wire, SDA=21, SCL=22)
//  Thay thế DHT22 trên board 30 chân
// =============================================================================

static Adafruit_AHTX0 aht;

bool aht10_init() {
    // AHT10 dùng chung bus Wire đã được khởi tạo bởi CCS811
    if (!aht.begin(&Wire, 0, AHT10_ADDR)) {
        LOG_MSG("AHT10", "THẤT BẠI! Không tìm thấy sensor.");
        return false;
    }

    LOG_MSG("AHT10", "Khởi tạo... OK!");
    return true;
}

bool aht10_read(int16_t* temperature, uint16_t* humidity) {
    *temperature = SENSOR_ERROR_I16;
    *humidity    = SENSOR_ERROR_U16;

    for (int attempt = 1; attempt <= SENSOR_READ_RETRIES; attempt++) {
        sensors_event_t humEvent, tempEvent;
        aht.getEvent(&humEvent, &tempEvent);

        float t = tempEvent.temperature;
        float h = humEvent.relative_humidity;

        if (!isnan(t) && !isnan(h)) {
            // Nhân ×10 chuyển về số nguyên theo thiết kế gói tin
            *temperature = (int16_t)(t * 10.0f);  // VD: 25.4°C → 254
            *humidity    = (uint16_t)(h * 10.0f);  // VD: 60.5%  → 605

            LOG_INFO("AHT10", "Nhiệt độ: %.1f°C | Độ ẩm: %.1f%%", t, h);
            return true;
        }

        LOG_INFO("AHT10", "Đọc lỗi, thử lại %d/%d", attempt, SENSOR_READ_RETRIES);
        delay(500);
    }

    LOG_MSG("AHT10", "THẤT BẠI! Trả về SENSOR_ERROR");
    return false;
}
