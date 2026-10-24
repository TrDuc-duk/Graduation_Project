#pragma once

// =============================================================================
//  LORA TASK - Gửi gói tin LoRa (FreeRTOS)
//  Core 1, Priority 3 (cao nhất)
// =============================================================================

/**
 * FreeRTOS task: Chờ SensorPayload từ Queue → gửi qua LoRa
 * Gửi Heartbeat nếu không nhận data quá 10 phút
 */
void loraTask(void* parameter);
