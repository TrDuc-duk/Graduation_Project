#include "sensor_task.h"
#include <Arduino.h>
#include "config.h"
#include "common/debug.h"
#include "common/packet.h"
#include "rtos/shared.h"
#include "core/nvs_config.h"
#include "drivers/pms7003.h"
#include "drivers/ccs811.h"
#include "drivers/aht10.h"
#include "drivers/oled_display.h"

// =============================================================================
//  SENSOR TASK IMPLEMENTATION
//  Chu kỳ hoạt động:
//    1. Bật PMS7003 fan (warm-up)
//    2. Đọc AHT10 + CCS811 song song với warm-up (tiết kiệm ~3s)
//    3. Chờ PMS7003 warm-up xong → đọc PM2.5/PM10
//    4. Đóng gói SensorPayload → gửi vào Queue
//    5. Ngủ 5 phút
// =============================================================================

void sensorTask(void* parameter) {
    SensorPayload payload;
    TickType_t warmupStart;

    LOG_INFO("TASK", "SensorTask started (Core %d)", xPortGetCoreID());

    while (true) {
        // ── Heartbeat cho WatchdogTask ──
        taskHeartbeat[TASK_SENSOR] = xTaskGetTickCount();

        LOG_SEPARATOR();
        LOG_MSG("SENSOR", "━━ Bắt đầu chu kỳ đo ━━");

        // Xoá payload trước mỗi chu kỳ
        memset(&payload, 0, sizeof(SensorPayload));

        // ═══════════════════════════════════════════
        // Giai đoạn 1: Bật PMS7003 warm-up
        // ═══════════════════════════════════════════
        pms7003_powerOn();
        warmupStart = xTaskGetTickCount();

        // ═══════════════════════════════════════════
        // Giai đoạn 2: Đọc AHT10 + CCS811 (song song với PMS warm-up)
        // Bọc mutex I2C để tránh xung đột với OLED update (Core 1)
        // ═══════════════════════════════════════════
        LOG_MSG("SENSOR", "Chờ PMS warm-up...");

        // AHT10
        int16_t  temp = SENSOR_ERROR_I16;
        uint16_t hum  = SENSOR_ERROR_U16;

        // CCS811
        uint16_t co2  = 0;
        uint16_t tvoc = 0;

        if (xSemaphoreTake(i2cMutex, pdMS_TO_TICKS(2000)) == pdTRUE) {
            // Tắt OLED để giảm nhiễu I2C bus khi đọc CCS811
            oled_sleep();
            delay(10);

            aht10_read(&temp, &hum);

            // CCS811: bù trừ nhiệt độ/độ ẩm (nếu AHT10 có dữ liệu)
            if (temp != SENSOR_ERROR_I16 && hum != SENSOR_ERROR_U16) {
                ccs811_setEnvData(temp, hum);
            }
            ccs811_read(&co2, &tvoc);

            // Bật lại OLED
            oled_wake();

            xSemaphoreGive(i2cMutex);
        } else {
            LOG_MSG("SENSOR", "⚠ I2C mutex timeout! Bỏ qua CCS811/AHT10.");
        }

        payload.temperature = temp;
        payload.humidity    = hum;
        payload.co2  = co2;
        payload.tvoc = tvoc;

        // ═══════════════════════════════════════════
        // Chờ PMS7003 warm-up xong
        // ═══════════════════════════════════════════
        TickType_t elapsed = xTaskGetTickCount() - warmupStart;
        TickType_t remaining = pdMS_TO_TICKS(PMS_WARMUP_MS) - elapsed;
        if (remaining > 0 && remaining < pdMS_TO_TICKS(PMS_WARMUP_MS)) {
            LOG_INFO("SENSOR", "Chờ PMS warm-up thêm %lu ms...",
                       (unsigned long)(remaining * portTICK_PERIOD_MS));
            vTaskDelay(remaining);
        }

        // ═══════════════════════════════════════════
        // Giai đoạn 3: Đọc PMS7003
        // ═══════════════════════════════════════════
        uint16_t pm1  = SENSOR_ERROR_U16;
        uint16_t pm25 = SENSOR_ERROR_U16;
        uint16_t pm10 = SENSOR_ERROR_U16;
        pms7003_read(&pm1, &pm25, &pm10);
        payload.pm1  = pm1;
        payload.pm25 = pm25;
        payload.pm10 = pm10;

        // Tắt quạt PMS7003 để tiết kiệm pin
        pms7003_powerOff();

        // ═══════════════════════════════════════════
        // Giai đoạn 4: Đóng gói header + gửi vào Queue
        // ═══════════════════════════════════════════
        payload.nodeId  = cfg_nodeId;
        payload.pktType = PKT_TYPE_DATA;
        payload.msgId   = msgCounter++;
        payload.battery = batteryLevel;  // Lấy từ BatteryTask

        // Cập nhật OLED display với dữ liệu mới
        oled_setSensorData(&payload);

        // Gửi vào Queue (timeout 1 giây)
        if (xQueueSend(dataQueue, &payload, pdMS_TO_TICKS(1000)) == pdTRUE) {
            LOG_INFO("SENSOR", "→ Queue OK (MsgID: %d)", payload.msgId);
        } else {
            LOG_MSG("SENSOR", "⚠ Queue đầy! Bỏ gói tin này.");
        }

        // Log tổng hợp
        LOG_MSG("SENSOR", "━━ Kết thúc chu kỳ đo ━━");
        LOG_INFO("SENSOR", "PM1:%.1f PM2.5:%.1f PM10:%.1f CO2:%d TVOC:%d T:%.1f H:%.1f Bat:%d%%",
            payload.pm1  == SENSOR_ERROR_U16 ? -1.0f : payload.pm1  / 10.0f,
            payload.pm25 == SENSOR_ERROR_U16 ? -1.0f : payload.pm25 / 10.0f,
            payload.pm10 == SENSOR_ERROR_U16 ? -1.0f : payload.pm10 / 10.0f,
            payload.co2, payload.tvoc,
            payload.temperature == SENSOR_ERROR_I16 ? -99.9f : payload.temperature / 10.0f,
            payload.humidity == SENSOR_ERROR_U16 ? -1.0f : payload.humidity / 10.0f,
            payload.battery);

        // ═══════════════════════════════════════════
        // Giai đoạn 5: Ngủ đến chu kỳ tiếp theo
        // Chia thành các giấc 30s, mỗi giấc cập nhật heartbeat
        // để WatchdogTask không báo treo
        // ═══════════════════════════════════════════
        LOG_INFO("SENSOR", "Ngủ %d phút...", SEND_INTERVAL_MS / 60000);
        {
            uint32_t sleepRemaining = SEND_INTERVAL_MS - PMS_WARMUP_MS;
            const uint32_t sleepChunk = 30000;  // 30 giây mỗi lần

            while (sleepRemaining > 0) {
                uint32_t thisDelay = (sleepRemaining > sleepChunk) ? sleepChunk : sleepRemaining;
                vTaskDelay(pdMS_TO_TICKS(thisDelay));
                sleepRemaining -= thisDelay;
                taskHeartbeat[TASK_SENSOR] = xTaskGetTickCount();
            }
        }
    }
}
