#pragma once

// =============================================================================
//  CCS811 DRIVER - Cảm biến CO2 / TVOC (Deep-Sleep Version)
//  Giao tiếp: I2C (Address 0x5A)
//  Hỗ trợ save/restore baseline qua RTC memory
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
 * Lưu CCS811 baseline vào RTC memory (gọi trước deep-sleep)
 */
void ccs811_saveBaseline();

/**
 * Tắt CCS811 heater (Drive Mode 0 + WAK HIGH) trước deep-sleep
 * Tiết kiệm ~26mA so với để Drive Mode 1 chạy liên tục
 */
void ccs811_sleep();

/**
 * Khôi phục CCS811 baseline từ RTC memory (gọi sau wake-up)
 */
void ccs811_restoreBaseline();
