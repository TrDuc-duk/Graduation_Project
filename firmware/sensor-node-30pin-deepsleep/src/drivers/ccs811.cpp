#include "ccs811.h"
#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_CCS811.h>
#include "config.h"
#include "common/debug.h"
#include "common/packet.h"

// =============================================================================
//  CCS811 DRIVER — Deep-Sleep Version
//  Dải đo: eCO2 400-8192 ppm, eTVOC 0-1187 ppb
//  Baseline được lưu/khôi phục qua RTC memory giữa các chu kỳ deep-sleep
// =============================================================================

static Adafruit_CCS811 ccs;

// RTC Memory — survive deep-sleep
extern RTC_DATA_ATTR uint16_t ccs811Baseline;
extern RTC_DATA_ATTR bool     hasBaseline;

bool ccs811_init() {
    // Khởi tạo chân điều khiển
    pinMode(CCS811_WAK_PIN, OUTPUT);
    pinMode(CCS811_ADD_PIN, OUTPUT);
    digitalWrite(CCS811_WAK_PIN, LOW);   // Wake sensor (active LOW)
    digitalWrite(CCS811_ADD_PIN, LOW);   // Address = 0x5A
    delay(200);

    if (!ccs.begin(CCS811_ADDR)) {
        LOG_MSG("CCS811", "THẤT BẠI! Không tìm thấy sensor.");
        return false;
    }

    // Đợi sensor sẵn sàng
    while (!ccs.available()) {
        delay(100);
    }

    // Drive mode 1: đo mỗi 1 giây (cần nhanh vì mỗi boot là cold start)
    ccs.setDriveMode(CCS811_DRIVE_MODE_1SEC);

    LOG_MSG("CCS811", "Khởi tạo... OK! (Drive Mode: 1s)");;
    return true;
}

void ccs811_setEnvData(int16_t temperature, uint16_t humidity) {
    float tempC = temperature / 10.0f;
    float humPct = humidity / 10.0f;
    ccs.setEnvironmentalData(humPct, tempC);
    LOG_INFO("CCS811", "ENV compensation: T=%.1f°C, H=%.1f%%", tempC, humPct);
}

bool ccs811_read(uint16_t* co2, uint16_t* tvoc) {
    *co2  = 0;
    *tvoc = 0;

    // Retry nhiều lần vì sau cold init, CCS811 thường trả 0 ở lần đọc đầu
    #define CCS811_MAX_RETRIES 10

    for (int attempt = 1; attempt <= CCS811_MAX_RETRIES; attempt++) {
        if (ccs.available()) {
            uint8_t err = ccs.readData();
            if (err == 0) {
                *co2  = ccs.geteCO2();
                *tvoc = ccs.getTVOC();

                // Lọc data rác
                if (*co2 > 8192 || *tvoc > 1187) {
                    LOG_INFO("CCS811", "⚠ Data rác (CO2:%d, TVOC:%d), đọc lại...", *co2, *tvoc);
                    *co2  = 0;
                    *tvoc = 0;
                    delay(500);
                    continue;
                }

                // Lọc data chưa sẵn sàng (CCS811 eCO2 tối thiểu là 400)
                if (*co2 < 400) {
                    LOG_INFO("CCS811", "Chưa có data thực (CO2:%d), chờ thêm...", *co2);
                    *co2 = 0;
                    *tvoc = 0;
                    delay(500);
                    continue;
                }

                LOG_INFO("CCS811", "CO2: %d ppm | TVOC: %d ppb", *co2, *tvoc);
                return true;
            } else {
                LOG_INFO("CCS811", "Lỗi đọc (err=%d), thử lại %d/%d",
                           err, attempt, CCS811_MAX_RETRIES);
            }
        } else {
            LOG_INFO("CCS811", "Chưa sẵn sàng, thử lại %d/%d",
                       attempt, CCS811_MAX_RETRIES);
        }
        delay(1000);
    }

    LOG_MSG("CCS811", "THẤT BẠI! Trả về 0");
    return false;
}

void ccs811_saveBaseline() {
    ccs811Baseline = ccs.getBaseline();
    hasBaseline = true;
    LOG_INFO("CCS811", "Baseline saved: 0x%04X", ccs811Baseline);
}

void ccs811_sleep() {
    // Tắt heater: Drive Mode 0 = Idle (không đo, heater tắt)
    ccs.setDriveMode(CCS811_DRIVE_MODE_IDLE);

    // Đặt WAK HIGH = sensor disable (tiết kiệm thêm)
    digitalWrite(CCS811_WAK_PIN, HIGH);

    LOG_MSG("CCS811", "Sleep (Drive Mode 0, WAK=HIGH)");
}

void ccs811_restoreBaseline() {
    if (hasBaseline) {
        ccs.setBaseline(ccs811Baseline);
        LOG_INFO("CCS811", "Baseline restored: 0x%04X", ccs811Baseline);
    } else {
        LOG_MSG("CCS811", "Chưa có baseline (lần đầu bật), cần warm-up ~20 phút");
    }
}
