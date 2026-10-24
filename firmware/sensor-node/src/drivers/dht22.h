#pragma once

// =============================================================================
//  DHT22 DRIVER - Cảm biến nhiệt độ / độ ẩm
//  Giao tiếp: 1-Wire (GPIO4)
// =============================================================================

#include <stdint.h>
#include <stdbool.h>

/**
 * Khởi tạo DHT22
 * @return true nếu khởi tạo thành công
 */
bool dht22_init();

/**
 * Đọc nhiệt độ và độ ẩm
 * Giá trị đã nhân ×10 để giữ 1 chữ số thập phân
 * @param temperature Con trỏ nhận nhiệt độ (°C × 10, int16_t - có dấu)
 * @param humidity    Con trỏ nhận độ ẩm (% × 10, uint16_t)
 * @return true nếu đọc thành công
 */
bool dht22_read(int16_t* temperature, uint16_t* humidity);
