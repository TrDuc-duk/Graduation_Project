#pragma once

// =============================================================================
//  SENSOR TASK - Đọc tất cả cảm biến (FreeRTOS)
//  Core 0, Priority 2
// =============================================================================

/**
 * FreeRTOS task: Đọc PMS7003, CCS811, DHT22 theo chu kỳ
 * Song song hóa: Đọc DHT22+CCS811 trong khi PMS7003 warm-up
 * Gửi SensorPayload vào dataQueue cho LoRaTask
 */
void sensorTask(void* parameter);
