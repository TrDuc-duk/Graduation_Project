#pragma once

// =============================================================================
//  BATTERY ADC DRIVER - Đo điện áp pin 18650
//  Giao tiếp: ADC (GPIO34), Voltage Divider 2×100KΩ
// =============================================================================

#include <stdint.h>

/**
 * Khởi tạo ADC cho đo pin
 */
void battery_init();

/**
 * Đọc phần trăm pin hiện tại
 * @return Phần trăm pin 0-100%
 */
uint8_t battery_readPercent();

/**
 * Đọc điện áp pin thực tế (V)
 * @return Điện áp pin (V)
 */
float battery_readVoltage();
