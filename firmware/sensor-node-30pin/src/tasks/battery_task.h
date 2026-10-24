#pragma once

// =============================================================================
//  BATTERY TASK - Giám sát pin (FreeRTOS)
//  Core 0, Priority 1 (thấp)
// =============================================================================

/**
 * FreeRTOS task: Đọc ADC pin mỗi 30 giây, cập nhật batteryLevel
 */
void batteryTask(void* parameter);
