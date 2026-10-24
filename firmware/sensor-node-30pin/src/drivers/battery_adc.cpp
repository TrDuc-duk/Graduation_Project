#include "battery_adc.h"
#include <Arduino.h>
#include "config.h"
#include "common/debug.h"

// =============================================================================
//  BATTERY ADC DRIVER IMPLEMENTATION
//  Voltage Divider: V_adc = V_battery × (R2 / (R1 + R2)) = V_battery × 0.5
//  ESP32 ADC: 12-bit (0-4095), tham chiếu ~3.3V
//  Pin 18650: 3.0V (hết) → 4.2V (đầy)
// =============================================================================

// ESP32 ADC có sai số phi tuyến, dùng lookup table cho chính xác hơn
// Nhưng cho đồ án, phép tính tuyến tính đủ dùng

void battery_init() {
    analogReadResolution(12);           // 12-bit ADC
    analogSetAttenuation(ADC_11db);     // Dải đo tối đa ~3.3V
    pinMode(BATTERY_ADC_PIN, INPUT);

    LOG_MSG("BATTERY", "Khởi tạo ADC... OK!");
}

float battery_readVoltage() {
    uint32_t adcSum = 0;

    // Đọc nhiều lần lấy trung bình để giảm nhiễu
    for (int i = 0; i < BATTERY_SAMPLES; i++) {
        adcSum += analogRead(BATTERY_ADC_PIN);
        delayMicroseconds(100);
    }

    float adcAvg = (float)adcSum / BATTERY_SAMPLES;

    // Chuyển đổi ADC → điện áp thực (có voltage divider)
    // V_adc = (adcAvg / 4095) × 3.3V
    // V_battery = V_adc × BATTERY_V_DIVIDER
    float vAdc = (adcAvg / 4095.0f) * 3.3f;
    float vBattery = vAdc * BATTERY_V_DIVIDER;

    return vBattery;
}

uint8_t battery_readPercent() {
    float voltage = battery_readVoltage();

    // Clamp và map điện áp sang phần trăm
    if (voltage >= BATTERY_V_MAX) return 100;
    if (voltage <= BATTERY_V_MIN) return 0;

    // Linear mapping: 3.0V = 0%, 4.2V = 100%
    float percent = (voltage - BATTERY_V_MIN) / (BATTERY_V_MAX - BATTERY_V_MIN) * 100.0f;
    uint8_t result = (uint8_t)percent;

    LOG_INFO("BATTERY", "V=%.2fV → %d%%", voltage, result);
    return result;
}
