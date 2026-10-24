#include "ccs811.h"
#include <Arduino.h>
#include <Adafruit_CCS811.h>
#include "config.h"
#include "common/debug.h"
#include "common/packet.h"

// =============================================================================
//  CCS811 DRIVER IMPLEMENTATION
//  Dải đo: eCO2 400-8192 ppm, eTVOC 0-1187 ppb
//  Lưu ý: Cần warm-up ~20 phút để dữ liệu chính xác
// =============================================================================

static Adafruit_CCS811 ccs;
static unsigned long ccs811StartTime = 0;

bool ccs811_init() {
    Wire.begin(CCS811_SDA_PIN, CCS811_SCL_PIN);

    if (!ccs.begin(CCS811_ADDR)) {
        LOG_MSG("CCS811", "THẤT BẠI! Không tìm thấy sensor.");
        return false;
    }

    // Đợi sensor sẵn sàng
    while (!ccs.available()) {
        delay(100);
    }

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

    ccs.setEnvironmentalData(humPct, tempC);
    LOG_INFO("CCS811", "ENV compensation: T=%.1f°C, H=%.1f%%", tempC, humPct);
}

bool ccs811_read(uint16_t* co2, uint16_t* tvoc) {
    *co2  = 0;
    *tvoc = 0;

    for (int attempt = 1; attempt <= SENSOR_READ_RETRIES; attempt++) {
        if (ccs.available()) {
            uint8_t err = ccs.readData();
            if (err == 0) {
                *co2  = ccs.geteCO2();
                *tvoc = ccs.getTVOC();

                LOG_INFO("CCS811", "CO2: %d ppm | TVOC: %d ppb", *co2, *tvoc);

                // Cảnh báo nếu chưa warm-up
                if (!ccs811_isWarmedUp()) {
                    LOG_MSG("CCS811", "⚠ Chưa warm-up đủ 20 phút, dữ liệu có thể chưa chính xác");
                }
                return true;
            } else {
                LOG_INFO("CCS811", "Lỗi đọc (err=%d), thử lại %d/%d",
                           err, attempt, SENSOR_READ_RETRIES);
            }
        } else {
            LOG_INFO("CCS811", "Chưa sẵn sàng, thử lại %d/%d",
                       attempt, SENSOR_READ_RETRIES);
        }
        delay(1000);
    }

    LOG_MSG("CCS811", "THẤT BẠI! Trả về 0");
    return false;
}

bool ccs811_isWarmedUp() {
    return (millis() - ccs811StartTime) >= CCS811_WARMUP_MS;
}
