#pragma once

// =============================================================================
//  WATCHDOG TASK - Giám sát heartbeat các task (FreeRTOS)
//  Core 0, Priority 0 (thấp nhất)
// =============================================================================

/**
 * FreeRTOS task: Kiểm tra heartbeat từ các task mỗi 10 giây
 * Nếu task nào không phản hồi quá WDT_TIMEOUT_MS → reset ESP32
 */
void watchdogTask(void* parameter);
