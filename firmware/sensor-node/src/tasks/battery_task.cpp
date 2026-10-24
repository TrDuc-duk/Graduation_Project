#include "battery_task.h"
#include <Arduino.h>
#include "config.h"
#include "common/debug.h"
#include "rtos/shared.h"
#include "drivers/battery_adc.h"

// =============================================================================
//  BATTERY TASK IMPLEMENTATION
//  Đọc ADC pin mỗi 30 giây, cập nhật biến volatile batteryLevel
//  SensorTask sẽ đọc giá trị này khi đóng gói payload
// =============================================================================

void batteryTask(void* parameter) {
    LOG_INFO("TASK", "BatteryTask started (Core %d)", xPortGetCoreID());

    while (true) {
        // ── Heartbeat cho WatchdogTask ──
        taskHeartbeat[TASK_BATTERY] = xTaskGetTickCount();

        // Đọc phần trăm pin
        uint8_t level = battery_readPercent();
        batteryLevel = level;  // Atomic write (1 byte, không cần mutex)

        // Đọc mỗi 30 giây
        vTaskDelay(pdMS_TO_TICKS(BATTERY_READ_INTERVAL_MS));
    }
}
