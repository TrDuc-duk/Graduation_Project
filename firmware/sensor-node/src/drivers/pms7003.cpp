#include "pms7003.h"
#include <Arduino.h>
#include <PMS.h>
#include "config.h"
#include "common/debug.h"
#include "common/packet.h"

// =============================================================================
//  PMS7003 DRIVER IMPLEMENTATION
//  Protocol: UART 9600 baud, 32-byte data frame
//  Đọc PM2.5 và PM10 (standard particle concentration)
// =============================================================================

static HardwareSerial pmsSerial(2);  // UART2
static PMS pms(pmsSerial);
static PMS::DATA pmsData;

bool pms7003_init() {
    // Khởi tạo UART2 với pins từ config
    pmsSerial.begin(9600, SERIAL_8N1, PMS_RX_PIN, PMS_TX_PIN);

    // Cấu hình chân SET để điều khiển nguồn PMS7003
    pinMode(PMS_SET_PIN, OUTPUT);
    digitalWrite(PMS_SET_PIN, HIGH);  // Bật mặc định

    // Đặt PMS7003 vào chế độ passive (chỉ đọc khi yêu cầu)
    pms.passiveMode();

    LOG_MSG("PMS7003", "Khởi tạo... OK!");
    return true;
}

void pms7003_powerOn() {
    digitalWrite(PMS_SET_PIN, HIGH);
    pms.wakeUp();
    LOG_MSG("PMS7003", "Bật quạt (warm-up)");
}

void pms7003_powerOff() {
    pms.sleep();
    digitalWrite(PMS_SET_PIN, LOW);
    LOG_MSG("PMS7003", "Tắt quạt (sleep)");
}

bool pms7003_read(uint16_t* pm1, uint16_t* pm25, uint16_t* pm10) {
    // Mặc định: giá trị lỗi
    *pm1  = SENSOR_ERROR_U16;
    *pm25 = SENSOR_ERROR_U16;
    *pm10 = SENSOR_ERROR_U16;

    // Thử đọc tối đa SENSOR_READ_RETRIES lần
    for (int attempt = 1; attempt <= SENSOR_READ_RETRIES; attempt++) {
        pms.requestRead();

        if (pms.readUntil(pmsData, 3000)) {  // Timeout 3 giây
            // PMS Library trả về giá trị nguyên (µg/m³)
            // Nhân ×10 theo thiết kế gói tin LoRa
            *pm1  = (uint16_t)(pmsData.PM_AE_UG_1_0 * 10);
            *pm25 = (uint16_t)(pmsData.PM_AE_UG_2_5 * 10);
            *pm10 = (uint16_t)(pmsData.PM_AE_UG_10_0 * 10);

            LOG_INFO("PMS7003", "PM1.0: %d | PM2.5: %d | PM10: %d (raw µg/m³)",
                        pmsData.PM_AE_UG_1_0, pmsData.PM_AE_UG_2_5, pmsData.PM_AE_UG_10_0);
            return true;
        }

        LOG_INFO("PMS7003", "Đọc lỗi, thử lại lần %d/%d", attempt, SENSOR_READ_RETRIES);
        delay(1000);
    }

    LOG_MSG("PMS7003", "THẤT BẠI! Trả về SENSOR_ERROR");
    return false;
}
