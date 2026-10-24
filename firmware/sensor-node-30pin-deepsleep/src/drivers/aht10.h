#pragma once

// =============================================================================
//  AHT10 DRIVER - Cảm biến nhiệt độ / độ ẩm (I2C)
//  Thay thế DHT22 trên board 30 chân
//  Giao tiếp: I2C (Address 0x38, chung bus Wire với CCS811 và OLED)
// =============================================================================

#include <stdint.h>
#include <stdbool.h>

/**
 * Khởi tạo AHT10
 * @return true nếu khởi tạo thành công
 */
bool aht10_init();

/**
 * Đọc nhiệt độ và độ ẩm
 * Giá trị đã nhân ×10 để giữ 1 chữ số thập phân
 * @param temperature Con trỏ nhận nhiệt độ (°C × 10, int16_t - có dấu)
 * @param humidity    Con trỏ nhận độ ẩm (% × 10, uint16_t)
 * @return true nếu đọc thành công
 */
bool aht10_read(int16_t* temperature, uint16_t* humidity);
