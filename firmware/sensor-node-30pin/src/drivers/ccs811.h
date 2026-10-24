#pragma once

// =============================================================================
//  CCS811 DRIVER - Cảm biến CO2 / TVOC
//  Giao tiếp: I2C (Address 0x5A)
// =============================================================================

#include <stdint.h>
#include <stdbool.h>

/**
 * Khởi tạo CCS811 (I2C)
 * @return true nếu khởi tạo thành công
 */
bool ccs811_init();

/**
 * Cung cấp dữ liệu nhiệt độ/độ ẩm cho CCS811 để bù trừ chính xác
 * (Environmental Data Compensation)
 * @param temperature Nhiệt độ (°C × 10, int16_t)
 * @param humidity    Độ ẩm (% × 10, uint16_t)
 */
void ccs811_setEnvData(int16_t temperature, uint16_t humidity);

/**
 * Đọc dữ liệu CO2 và TVOC
 * @param co2  Con trỏ nhận giá trị eCO2 (ppm)
 * @param tvoc Con trỏ nhận giá trị eTVOC (ppb)
 * @return true nếu đọc thành công
 */
bool ccs811_read(uint16_t* co2, uint16_t* tvoc);

/**
 * Kiểm tra CCS811 đã warm-up xong chưa (cần ~20 phút)
 * @return true nếu đã sẵn sàng cho dữ liệu chính xác
 */
bool ccs811_isWarmedUp();
