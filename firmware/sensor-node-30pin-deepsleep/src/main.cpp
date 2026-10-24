#include <Arduino.h>
#include <Wire.h>
#include <esp_sleep.h>

#include "config.h"
#include "common/packet.h"
#include "common/debug.h"

// Core
#include "core/nvs_config.h"

// Provisioning
#include "provisioning/captive_portal.h"

// Drivers
#include "drivers/lora_radio.h"
#include "drivers/pms7003.h"
#include "drivers/ccs811.h"
#include "drivers/aht10.h"
#include "drivers/battery_adc.h"
#include "drivers/oled_display.h"

// =============================================================================
//  MAIN.CPP — Air Quality Sensor Node (Deep-Sleep Version)
//
//  Kiến trúc:
//    Timer wakeup  → Init → Đo sensor → Gửi LoRa → Deep-sleep 5 phút
//    Button wakeup → Hiện OLED 10s (data cũ) → Deep-sleep lại
//    loop()        → Không bao giờ chạy
//
//  Mỗi lần thức dậy từ deep-sleep, ESP32 chạy lại setup() từ đầu.
//  Trạng thái được lưu qua RTC memory (survive deep-sleep).
// =============================================================================

// ===== RTC Memory — survive deep-sleep =====
RTC_DATA_ATTR uint8_t       msgCounter    = 0;
RTC_DATA_ATTR uint16_t      ccs811Baseline = 0;
RTC_DATA_ATTR bool          hasBaseline   = false;
RTC_DATA_ATTR uint32_t      bootCount     = 0;
RTC_DATA_ATTR SensorPayload lastPayload;       // Lưu data gần nhất để hiện khi nhấn nút
RTC_DATA_ATTR bool          hasLastPayload = false;
RTC_DATA_ATTR bool          lastLoraSent   = false;

// ===== Vào deep-sleep (dùng chung) =====
static void enterDeepSleep() {
    Serial.printf("\n[SLEEP] Deep-sleep %llu phút... ZZZ\n\n", DEEP_SLEEP_US / 60000000ULL);
    Serial.flush();

    esp_sleep_enable_timer_wakeup(DEEP_SLEEP_US);
    esp_sleep_enable_ext0_wakeup(GPIO_NUM_0, 0);  // Nhấn BOOT (LOW) → wake
    esp_deep_sleep_start();
}

// ===== Xử lý wake-up bằng nút BOOT =====
static void handleButtonWakeup() {
    LOG_MSG("WAKE", "Thức dậy do nhấn nút BOOT");

    if (hasLastPayload) {
        // Hiện data gần nhất trên OLED
        Wire.begin(CCS811_SDA_PIN, CCS811_SCL_PIN);
        delay(50);
        oled_init();
        oled_setSensorData(&lastPayload);
        oled_setLoRaStatus(lastLoraSent);
        oled_showData();

        LOG_INFO("OLED", "Hiển thị data cũ %ds...", OLED_DISPLAY_DURATION_MS / 1000);
        delay(OLED_DISPLAY_DURATION_MS);
        oled_sleep();
    } else {
        LOG_MSG("OLED", "Chưa có data (lần đầu bật). Bỏ qua.");
    }

    // Quay lại deep-sleep (KHÔNG đo, KHÔNG gửi LoRa)
    enterDeepSleep();
}

// ===== Khởi tạo phần cứng (I2C + tất cả sensor) =====
static bool initHardware() {
    bool allOk = true;

    // I2C bus — chung cho OLED, CCS811, AHT10
    Wire.begin(CCS811_SDA_PIN, CCS811_SCL_PIN);
    Wire.setClock(100000);  // 100KHz (không cần hạ 10KHz vì không có OLED contention)
    delay(50);

    // LoRa AS32-TTL-100
    Serial.print("[LoRa] Đang khởi tạo... ");
    if (lora_init()) {
        Serial.println("OK!");
    } else {
        Serial.println("THẤT BẠI!");
        allOk = false;
    }

    // PMS7003
    Serial.print("[PMS7003] Đang khởi tạo... ");
    if (pms7003_init()) {
        Serial.println("OK!");
    } else {
        Serial.println("THẤT BẠI!");
        allOk = false;
    }

    // CCS811
    Serial.print("[CCS811] Đang khởi tạo... ");
    if (ccs811_init()) {
        Serial.println("OK!");
    } else {
        Serial.println("THẤT BẠI!");
        allOk = false;
    }

    // AHT10
    Serial.print("[AHT10] Đang khởi tạo... ");
    if (aht10_init()) {
        Serial.println("OK!");
    } else {
        Serial.println("THẤT BẠI!");
        allOk = false;
    }

    // Battery ADC
    battery_init();
    Serial.println("[Battery] ADC OK!");

    return allOk;
}

// ===== Kiểm tra factory reset (nhấn giữ nút BOOT) =====
static void checkFactoryReset() {
    pinMode(RESET_BUTTON_PIN, INPUT_PULLUP);
    delay(50);  // Debounce

    if (digitalRead(RESET_BUTTON_PIN) == LOW) {
        // Nút đang được nhấn — chờ xem có giữ đủ lâu không
        unsigned long pressStart = millis();

        while (digitalRead(RESET_BUTTON_PIN) == LOW) {
            if (millis() - pressStart >= RESET_HOLD_TIME_MS) {
                LOG_MSG("RESET", "═══ FACTORY RESET ═══");

                // LED nhấp nháy
                pinMode(LED_PROVISION_PIN, OUTPUT);
                for (int i = 0; i < 10; i++) {
                    digitalWrite(LED_PROVISION_PIN, i % 2);
                    delay(100);
                }

                nvs_clearConfig();
                delay(1000);
                ESP.restart();
            }
            delay(50);
        }
    }
}



void setup() {
    Serial.begin(115200);
    delay(500);

    bootCount++;

    // ── 1. Đọc cấu hình từ NVS ──
    nvs_loadConfig();

    // ── 2. Kiểm tra provisioning ──
    if (!nvs_isProvisioned()) {
        // Chế độ Provisioning — KHÔNG deep-sleep
        Wire.begin(CCS811_SDA_PIN, CCS811_SCL_PIN);
        delay(50);
        oled_init();
        oled_showProvisioning();
        startCaptivePortal();
        return;  // Không bao giờ đến đây
    }

    // ── 3. Kiểm tra lý do thức dậy ──
    esp_sleep_wakeup_cause_t wakeupCause = esp_sleep_get_wakeup_cause();
    if (wakeupCause == ESP_SLEEP_WAKEUP_EXT0) {
        // Nhấn nút BOOT → hiện OLED rồi quay lại sleep
        handleButtonWakeup();
        return;  // Không bao giờ đến đây (đã deep-sleep)
    }

    // ── 4. Kiểm tra factory reset ──
    checkFactoryReset();

    // ═══ CHẾ ĐỘ ĐO + GỬI + DEEP-SLEEP ═══
    Serial.println();
    Serial.println("========================================");
    Serial.println("  AIR QUALITY SENSOR (Deep-Sleep)");
    Serial.printf("  Node ID  : 0x%02X (%s)\n", cfg_nodeId, cfg_nodeIdStr);
    Serial.printf("  Boot #   : %d\n", bootCount);
    Serial.printf("  Sleep    : %llu phút\n", DEEP_SLEEP_US / 60000000ULL);
    Serial.println("========================================");

    // ── 4. Init phần cứng ──
    bool hwOk = initHardware();
    if (!hwOk) {
        Serial.println("[WARN] Một số module lỗi. Tiếp tục...");
    }

    // ── 5. Bật PMS7003 warm-up ──
    pms7003_powerOn();
    unsigned long warmupStart = millis();

    // ── 6. Trong khi chờ PMS warm-up → đọc AHT10 + CCS811 ──
    LOG_MSG("SENSOR", "Đọc AHT10 + CCS811 (song song PMS warm-up)...");

    int16_t  temp = SENSOR_ERROR_I16;
    uint16_t hum  = SENSOR_ERROR_U16;
    uint16_t co2  = 0;
    uint16_t tvoc = 0;

    // AHT10
    aht10_read(&temp, &hum);

    // CCS811: khôi phục baseline + đọc
    ccs811_restoreBaseline();
    if (temp != SENSOR_ERROR_I16 && hum != SENSOR_ERROR_U16) {
        ccs811_setEnvData(temp, hum);
    }

    // Chờ CCS811 có measurement đầu tiên dồi dào hơn (drive mode 1s)
    // Delay 5s nằm trong thời gian 30s chờ PMS warm-up nên KHÔNG làm tăng tổng thời gian thức
    delay(30000);
    ccs811_read(&co2, &tvoc);

    // ── 7. Chờ PMS warm-up xong → đọc PM ──
    unsigned long elapsed = millis() - warmupStart;
    if (elapsed < PMS_WARMUP_MS) {
        unsigned long remaining = PMS_WARMUP_MS - elapsed;
        LOG_INFO("SENSOR", "Chờ PMS warm-up thêm %lu ms...", remaining);
        delay(remaining);
    }

    uint16_t pm1  = SENSOR_ERROR_U16;
    uint16_t pm25 = SENSOR_ERROR_U16;
    uint16_t pm10 = SENSOR_ERROR_U16;
    pms7003_read(&pm1, &pm25, &pm10);

    // Tắt PMS7003
    pms7003_powerOff();

    // ── 8. Đọc battery ──
    uint8_t battery = battery_readPercent();

    // ── 9. Đóng gói payload ──
    SensorPayload payload;
    memset(&payload, 0, sizeof(SensorPayload));
    payload.nodeId      = cfg_nodeId;
    payload.pktType     = PKT_TYPE_DATA;
    payload.msgId       = msgCounter++;
    payload.pm1         = pm1;
    payload.pm25        = pm25;
    payload.pm10        = pm10;
    payload.co2         = co2;
    payload.tvoc        = tvoc;
    payload.temperature = temp;
    payload.humidity    = hum;
    payload.battery     = battery;

    // ── 10. Gửi LoRa ──
    bool sent = false;
    for (int attempt = 1; attempt <= 2; attempt++) {
        if (lora_sendPacket(&payload)) {
            sent = true;
            break;
        }
        LOG_INFO("LoRa TX", "Gửi lỗi, thử lại %d/2", attempt);
        delay(500);
    }

    if (sent) {
        LOG_INFO("LoRa TX", "OK! MsgID:%d PM2.5:%.1f CO2:%d T:%.1f Bat:%d%%",
            payload.msgId,
            pm25 == SENSOR_ERROR_U16 ? -1.0f : pm25 / 10.0f,
            co2,
            temp == SENSOR_ERROR_I16 ? -99.9f : temp / 10.0f,
            battery);
    } else {
        LOG_MSG("LoRa TX", "THẤT BẠI sau 2 lần thử!");
    }

    // LoRa sleep
    lora_sleep();

    // ── 11. Lưu CCS811 baseline + tắt heater ──
    ccs811_saveBaseline();
    ccs811_sleep();

    // ── 12. Lưu payload vào RTC memory (để hiện OLED khi nhấn nút) ──
    memcpy(&lastPayload, &payload, sizeof(SensorPayload));
    hasLastPayload = true;
    lastLoraSent = sent;

    // ── 13. Log tổng hợp ──
    LOG_SEPARATOR();
    LOG_INFO("SENSOR", "PM1:%.1f PM2.5:%.1f PM10:%.1f CO2:%d TVOC:%d T:%.1f H:%.1f Bat:%d%%",
        pm1  == SENSOR_ERROR_U16 ? -1.0f : pm1  / 10.0f,
        pm25 == SENSOR_ERROR_U16 ? -1.0f : pm25 / 10.0f,
        pm10 == SENSOR_ERROR_U16 ? -1.0f : pm10 / 10.0f,
        co2, tvoc,
        temp == SENSOR_ERROR_I16 ? -99.9f : temp / 10.0f,
        hum  == SENSOR_ERROR_U16 ? -1.0f : hum  / 10.0f,
        battery);

    // ── 14. DEEP SLEEP ──
    enterDeepSleep();

    // Không bao giờ đến đây
}

void loop() {
    // Không bao giờ chạy — ESP32 deep-sleep sau setup()
}
