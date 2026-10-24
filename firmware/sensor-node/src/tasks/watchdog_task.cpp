#include "watchdog_task.h"
#include <Arduino.h>
#include <esp_system.h>
#include "config.h"
#include "common/debug.h"
#include "rtos/shared.h"

// =============================================================================
//  WATCHDOG TASK IMPLEMENTATION
//  Kiểm tra heartbeat từ các task mỗi 10 giây
//  Nếu task không cập nhật heartbeat quá WDT_TIMEOUT_MS → reset ESP32
//
//  Lưu ý: Cho phép "grace period" 2 phút sau boot để các task khởi tạo
// =============================================================================

static const char* taskNames[] = {"Sensor", "LoRa", "Battery"};

#define WDT_CHECK_INTERVAL_MS  10000   // Kiểm tra mỗi 10 giây
#define WDT_GRACE_PERIOD_MS    120000  // 2 phút grace period sau boot

void watchdogTask(void* parameter) {
    LOG_INFO("TASK", "WatchdogTask started (Core %d)", xPortGetCoreID());

    // Grace period: Chờ 2 phút cho tất cả task khởi tạo xong
    // (CCS811 warm-up, PMS7003 warm-up lần đầu, v.v.)
    vTaskDelay(pdMS_TO_TICKS(WDT_GRACE_PERIOD_MS));
    LOG_MSG("WDT", "Grace period kết thúc, bắt đầu giám sát.");

    while (true) {
        TickType_t now = xTaskGetTickCount();
        bool allHealthy = true;

        for (int i = 0; i < TASK_COUNT; i++) {
            TickType_t lastBeat = taskHeartbeat[i];

            // Nếu task chưa bao giờ heartbeat → bỏ qua
            if (lastBeat == 0) continue;

            TickType_t elapsed = now - lastBeat;
            uint32_t elapsedMs = elapsed * portTICK_PERIOD_MS;

            if (elapsedMs > WDT_TIMEOUT_MS) {
                allHealthy = false;
                LOG_INFO("WDT", "⚠ CẢNH BÁO: %s task không phản hồi! "
                           "(Elapsed: %lu ms, Timeout: %d ms)",
                           taskNames[i], elapsedMs, WDT_TIMEOUT_MS);
            }
        }

        if (!allHealthy) {
            LOG_MSG("WDT", "🔴 Task treo phát hiện! Restart ESP32...");
            vTaskDelay(pdMS_TO_TICKS(1000));  // Đợi Serial flush
            esp_restart();
        }

        vTaskDelay(pdMS_TO_TICKS(WDT_CHECK_INTERVAL_MS));
    }
}
