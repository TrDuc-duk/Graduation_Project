#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/queue.h>

#include "config.h"
#include "common/packet.h"
#include "common/debug.h"
#include "rtos/shared.h"

// Core
#include "core/nvs_config.h"

// Provisioning
#include "provisioning/captive_portal.h"

// Drivers
#include "drivers/lora_radio.h"
#include "drivers/pms7003.h"
#include "drivers/ccs811.h"
#include "drivers/dht22.h"
#include "drivers/battery_adc.h"
#include "drivers/oled_display.h"

// FreeRTOS Tasks
#include "tasks/sensor_task.h"
#include "tasks/lora_task.h"
#include "tasks/battery_task.h"
#include "tasks/watchdog_task.h"

// =============================================================================
//  MAIN.CPP - Air Quality Monitoring Sensor Node (FreeRTOS)
//
//  Kiến trúc:
//    setup() → Kiểm tra NVS → Provisioning hoặc Normal Mode
//    loop()  → Trống (logic trong FreeRTOS tasks)
//
//  Chế độ mới:
//    - Provisioning: Captive Portal khi chưa cấu hình
//    - Factory Reset: Giữ nút BOOT 5 giây
// =============================================================================

// ===== FreeRTOS Shared Resources (định nghĩa từ shared.h) =====
QueueHandle_t dataQueue = NULL;
volatile uint8_t batteryLevel = 0;
volatile TickType_t taskHeartbeat[TASK_COUNT] = {0};
RTC_DATA_ATTR uint8_t msgCounter = 0;

// ===== Factory Reset Task =====
// Chạy trên Core 0, kiểm tra nút BOOT liên tục
void factoryResetTask(void *parameter)
{
    pinMode(RESET_BUTTON_PIN, INPUT_PULLUP);
    unsigned long pressStart = 0;
    bool pressed = false;

    while (true)
    {
        bool btnState = (digitalRead(RESET_BUTTON_PIN) == LOW);

        if (btnState && !pressed)
        {
            pressed = true;
            pressStart = millis();
        }
        else if (!btnState && pressed)
        {
            pressed = false;
        }
        else if (btnState && pressed)
        {
            if (millis() - pressStart >= RESET_HOLD_TIME_MS)
            {
                LOG_MSG("RESET", "═══ FACTORY RESET ═══");

                // LED nhấp nháy
                pinMode(LED_PROVISION_PIN, OUTPUT);
                for (int i = 0; i < 10; i++)
                {
                    digitalWrite(LED_PROVISION_PIN, i % 2);
                    vTaskDelay(pdMS_TO_TICKS(100));
                }

                nvs_clearConfig();
                vTaskDelay(pdMS_TO_TICKS(1000));
                ESP.restart();
            }
        }

        vTaskDelay(pdMS_TO_TICKS(100)); // Kiểm tra mỗi 100ms
    }
}

// ===== Khởi tạo tất cả phần cứng =====
bool initAllHardware()
{
    bool allOk = true;

    // OLED Display (Wire1, I2C riêng)
    Serial.print("[OLED] Đang khởi tạo... ");
    if (oled_init()) {
        Serial.println("OK!");
    } else {
        Serial.println("THẤT BẠI! (tiếp tục không OLED)");
    }

    // LoRa AS32-TTL-100 (UART)
    Serial.print("[LoRa] Đang khởi tạo... ");
    if (lora_init())
    {
        Serial.println("OK!");
    }
    else
    {
        Serial.println("THẤT BẠI!");
        allOk = false;
    }

    // PMS7003 (UART2)
    Serial.print("[PMS7003] Đang khởi tạo... ");
    if (pms7003_init())
    {
        Serial.println("OK!");
    }
    else
    {
        Serial.println("THẤT BẠI!");
        allOk = false;
    }

    // CCS811 (I2C)
    Serial.print("[CCS811] Đang khởi tạo... ");
    if (ccs811_init()) {
        Serial.println("OK!");
    } else {
        Serial.println("THẤT BẠI!");
        allOk = false;
    }

    // TODO: DHT22 (GPIO) — chưa kết nối
    // Serial.print("[DHT22] Đang khởi tạo... ");
    // if (dht22_init()) {
    //     Serial.println("OK!");
    // } else {
    //     Serial.println("THẤT BẠI!");
    //     allOk = false;
    // }

    // Battery ADC
    battery_init();
    Serial.println("[Battery] ADC OK!");

    return allOk;
}

void setup()
{
    Serial.begin(115200);
    delay(1000); // Đợi Serial ổn định

    // ── 1. Đọc cấu hình từ NVS ──
    nvs_loadConfig();

    // ── 2. Kiểm tra đã provisioned chưa ──
    if (!nvs_isProvisioned())
    {
        // ═══ CHẾ ĐỘ PROVISIONING ═══
        // Hiển thị màn hình setup trên OLED
        oled_init();
        oled_showProvisioning();

        // WiFi AP tạm → user cấu hình → đăng ký server → lưu NVS → tắt WiFi → reboot
        startCaptivePortal();
        return; // Không bao giờ đến đây
    }

    // ═══ CHẾ ĐỘ BÌNH THƯỜNG (LoRa-only) ═══
    Serial.println();
    Serial.println("========================================");
    Serial.println("  AIR QUALITY SENSOR NODE (FreeRTOS)");
    Serial.printf("  Node ID  : 0x%02X (%s)\n", cfg_nodeId, cfg_nodeIdStr);
    Serial.printf("  Gateway  : %s\n", cfg_gatewayId);
    Serial.printf("  Interval : %d phút\n", SEND_INTERVAL_MS / 60000);
    Serial.printf("  LoRa     : AS32-TTL-100 (UART %d baud)\n", LORA_BAUD);
    Serial.println("========================================");

    // ── 3. Init tất cả phần cứng ──
    bool hwOk = initAllHardware();

    // Hiển thị Boot Screen trên OLED
    oled_showBoot();

    if (hwOk)
    {
        Serial.println("[OK] Tất cả module đã khởi tạo xong!");
    }
    else
    {
        Serial.println("[WARN] Một số module khởi tạo lỗi. Tiếp tục với chức năng có sẵn...");
    }

    // ── 4. Tạo FreeRTOS Queue ──
    dataQueue = xQueueCreate(DATA_QUEUE_SIZE, sizeof(SensorPayload));
    if (dataQueue == NULL)
    {
        Serial.println("[ERROR] Không tạo được Queue! Restart...");
        delay(3000);
        esp_restart();
    }
    Serial.printf("[Queue] Tạo Queue thành công (%d slots × %d bytes)\n",
                  DATA_QUEUE_SIZE, sizeof(SensorPayload));

    // ── 5. Tạo FreeRTOS Tasks ──
    Serial.println("[RTOS] Đang tạo tasks...");

    BaseType_t ret;

    ret = xTaskCreatePinnedToCore(
        sensorTask, "Sensor",
        SENSOR_TASK_STACK, NULL,
        SENSOR_TASK_PRIORITY, NULL,
        SENSOR_TASK_CORE);
    Serial.printf("  SensorTask  : %s (Core %d, Priority %d, Stack %d)\n",
                  ret == pdPASS ? "OK" : "FAIL",
                  SENSOR_TASK_CORE, SENSOR_TASK_PRIORITY, SENSOR_TASK_STACK);

    ret = xTaskCreatePinnedToCore(
        loraTask, "LoRa",
        LORA_TASK_STACK, NULL,
        LORA_TASK_PRIORITY, NULL,
        LORA_TASK_CORE);
    Serial.printf("  LoRaTask    : %s (Core %d, Priority %d, Stack %d)\n",
                  ret == pdPASS ? "OK" : "FAIL",
                  LORA_TASK_CORE, LORA_TASK_PRIORITY, LORA_TASK_STACK);

    ret = xTaskCreatePinnedToCore(
        batteryTask, "Battery",
        BATTERY_TASK_STACK, NULL,
        BATTERY_TASK_PRIORITY, NULL,
        BATTERY_TASK_CORE);
    Serial.printf("  BatteryTask : %s (Core %d, Priority %d, Stack %d)\n",
                  ret == pdPASS ? "OK" : "FAIL",
                  BATTERY_TASK_CORE, BATTERY_TASK_PRIORITY, BATTERY_TASK_STACK);

    ret = xTaskCreatePinnedToCore(
        watchdogTask, "WDT",
        WDT_TASK_STACK, NULL,
        WDT_TASK_PRIORITY, NULL,
        WDT_TASK_CORE);
    Serial.printf("  WatchdogTask: %s (Core %d, Priority %d, Stack %d)\n",
                  ret == pdPASS ? "OK" : "FAIL",
                  WDT_TASK_CORE, WDT_TASK_PRIORITY, WDT_TASK_STACK);

    // Factory Reset Task — kiểm tra nút BOOT
    ret = xTaskCreatePinnedToCore(
        factoryResetTask, "Reset",
        2048, NULL,
        1, NULL, // Priority 1
        0);
    Serial.printf("  ResetTask   : %s (giữ BOOT %ds = factory reset)\n",
                  ret == pdPASS ? "OK" : "FAIL",
                  RESET_HOLD_TIME_MS / 1000);

    Serial.println();
    Serial.println("========================================");
    Serial.println("  [OK] Hệ thống đã sẵn sàng!");
    Serial.println("  Tất cả logic chạy trong FreeRTOS tasks.");
    Serial.println("========================================");
    Serial.println();
}

void loop()
{
    // Cập nhật OLED display (tự throttle theo OLED_UPDATE_MS)
    oled_update();
    delay(100);
}
