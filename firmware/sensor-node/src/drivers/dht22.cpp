#include "dht22.h"
#include <Arduino.h>
#include <DHT.h>
#include "config.h"
#include "common/debug.h"
#include "common/packet.h"

// =============================================================================
//  DHT22 DRIVER IMPLEMENTATION
//  Dải đo: Nhiệt độ -40~80°C (±0.5°C), Độ ẩm 0~100% (±2%)
//  Khoảng cách đọc tối thiểu: 2 giây
// =============================================================================

static DHT dht(DHT_PIN, DHT_TYPE);

bool dht22_init() {
    dht.begin();
    delay(2000);  // DHT22 cần 2 giây sau khi bật nguồn

    // Test đọc lần đầu
    float t = dht.readTemperature();
    if (isnan(t)) {
        LOG_MSG("DHT22", "THẤT BẠI! Không đọc được dữ liệu.");
        return false;
    }

    LOG_MSG("DHT22", "Khởi tạo... OK!");
    return true;
}

bool dht22_read(int16_t* temperature, uint16_t* humidity) {
    *temperature = SENSOR_ERROR_I16;
    *humidity    = SENSOR_ERROR_U16;

    for (int attempt = 1; attempt <= SENSOR_READ_RETRIES; attempt++) {
        float t = dht.readTemperature();
        float h = dht.readHumidity();

        if (!isnan(t) && !isnan(h)) {
            // Nhân ×10 chuyển về số nguyên theo thiết kế gói tin
            *temperature = (int16_t)(t * 10.0f);  // VD: 25.4°C → 254
            *humidity    = (uint16_t)(h * 10.0f);  // VD: 60.5%  → 605

            LOG_INFO("DHT22", "Nhiệt độ: %.1f°C | Độ ẩm: %.1f%%", t, h);
            return true;
        }

        LOG_INFO("DHT22", "Đọc lỗi, thử lại %d/%d", attempt, SENSOR_READ_RETRIES);
        delay(2000);  // DHT22 cần ít nhất 2s giữa các lần đọc
    }

    LOG_MSG("DHT22", "THẤT BẠI! Trả về SENSOR_ERROR");
    return false;
}
