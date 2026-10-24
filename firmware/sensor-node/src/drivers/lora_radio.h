#pragma once

// =============================================================================
//  LORA RADIO DRIVER - AS32-TTL-100 (UART)
//  Module LoRa 433MHz, giao tiếp UART transparent
//  API giữ nguyên tương thích với sensor_task + lora_task
// =============================================================================

#include <stdint.h>
#include <stdbool.h>
#include "common/packet.h"

/**
 * Khởi tạo module AS32-TTL-100
 * - Init UART (Serial1 remap GPIO32/33)
 * - Cấu hình MD0/MD1 = Normal mode (0,0)
 * - Chờ AUX HIGH (module sẵn sàng)
 * @return true nếu khởi tạo thành công
 */
bool lora_init();

/**
 * Gửi gói tin SensorPayload (18 bytes) qua LoRa
 * Chờ AUX HIGH → write UART → chờ AUX HIGH (gửi xong)
 * @param payload Con trỏ tới struct SensorPayload
 * @return true nếu gửi thành công
 */
bool lora_sendPacket(const SensorPayload* payload);

/**
 * Đưa module vào chế độ Sleep (MD0=1, MD1=1)
 */
void lora_sleep();

/**
 * Đánh thức module về Normal mode (MD0=0, MD1=0)
 */
void lora_wakeup();
