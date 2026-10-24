#pragma once

// =============================================================================
//  PMS7003 DRIVER - Cảm biến bụi mịn PM2.5/PM10
//  Giao tiếp: UART2 (9600 baud)
// =============================================================================

#include <stdint.h>
#include <stdbool.h>

/**
 * Khởi tạo PMS7003 (UART2)
 * @return true nếu khởi tạo thành công
 */
bool pms7003_init();

/**
 * Bật quạt hút PMS7003 (chân SET = HIGH)
 * Cần chờ warm-up ~30 giây trước khi đọc dữ liệu
 */
void pms7003_powerOn();

/**
 * Tắt quạt hút PMS7003 (chân SET = LOW) để tiết kiệm pin
 */
void pms7003_powerOff();

/**
 * Đọc dữ liệu PM1.0, PM2.5 và PM10 từ PMS7003
 * Giá trị đã nhân ×10 để giữ 1 chữ số thập phân
 * @param pm1  Con trỏ nhận giá trị PM1.0 (µg/m³ × 10)
 * @param pm25 Con trỏ nhận giá trị PM2.5 (µg/m³ × 10)
 * @param pm10 Con trỏ nhận giá trị PM10  (µg/m³ × 10)
 * @return true nếu đọc thành công, false nếu lỗi (giá trị = SENSOR_ERROR_U16)
 */
bool pms7003_read(uint16_t* pm1, uint16_t* pm25, uint16_t* pm10);
