/**
 * TEST: Battery ADC - Đo điện áp pin 18650
 * Giao tiếp: ADC (GPIO34), Voltage Divider 2×100KΩ
 * 
 * Flash: pio run -e test_battery -t upload && pio device monitor
 * 
 * PASS khi: ADC raw > 0, điện áp 3.0~4.2V (có pin) hoặc ~0V (không pin)
 */

#include <Arduino.h>
#include "config.h"

void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("========================================");
    Serial.println("  TEST: Battery ADC (Pin 18650)");
    Serial.printf("  ADC Pin: GPIO%d\n", BATTERY_ADC_PIN);
    Serial.printf("  Samples: %d (lấy trung bình)\n", BATTERY_SAMPLES);
    Serial.printf("  Voltage Divider: %.1f (R1=R2=100K)\n", BATTERY_V_DIVIDER);
    Serial.printf("  Range: %.1fV (hết) → %.1fV (đầy)\n", BATTERY_V_MIN, BATTERY_V_MAX);
    Serial.println("========================================");
    Serial.println();

    // Init ADC
    analogReadResolution(12);
    analogSetAttenuation(ADC_11db);
    pinMode(BATTERY_ADC_PIN, INPUT);
    Serial.println("[BATTERY] ✅ ADC INIT OK!");
    Serial.println();

    Serial.println("[BATTERY] Bắt đầu đọc liên tục mỗi 2 giây...");
    Serial.println("─────────────────────────────────────────────────────");
    Serial.println("  #  │ ADC Raw │  V_adc  │ V_batt  │  Pin  │ Kết quả");
    Serial.println("─────────────────────────────────────────────────────");
}

static uint16_t readCount = 0;

void loop() {
    readCount++;

    // Đọc ADC nhiều lần lấy trung bình
    uint32_t adcSum = 0;
    uint16_t adcMin = 4095, adcMax = 0;

    for (int i = 0; i < BATTERY_SAMPLES; i++) {
        uint16_t val = analogRead(BATTERY_ADC_PIN);
        adcSum += val;
        if (val < adcMin) adcMin = val;
        if (val > adcMax) adcMax = val;
        delayMicroseconds(100);
    }

    float adcAvg = (float)adcSum / BATTERY_SAMPLES;

    // Tính điện áp
    float vAdc = (adcAvg / 4095.0f) * 3.3f;
    float vBattery = vAdc * BATTERY_V_DIVIDER;

    // Tính phần trăm
    uint8_t percent = 0;
    if (vBattery >= BATTERY_V_MAX) {
        percent = 100;
    } else if (vBattery > BATTERY_V_MIN) {
        percent = (uint8_t)((vBattery - BATTERY_V_MIN) / (BATTERY_V_MAX - BATTERY_V_MIN) * 100.0f);
    }

    // Đánh giá
    const char* status;
    if (adcAvg < 10) {
        status = "⚠ NO PIN";
    } else if (vBattery >= BATTERY_V_MIN && vBattery <= BATTERY_V_MAX) {
        status = "✅ PASS ";
    } else if (vBattery < BATTERY_V_MIN) {
        status = "🔴 LOW  ";
    } else {
        status = "⚠ HIGH ";
    }

    Serial.printf(" %3d │  %4.0f   │ %5.2fV  │ %5.2fV  │ %3d%%  │ %s\n",
                   readCount, adcAvg, vAdc, vBattery, percent, status);

    // Mỗi 10 lần, in thêm thông tin min/max ADC
    if (readCount % 10 == 0) {
        Serial.printf("     │ (ADC range: %d~%d, spread: %d)\n",
                       adcMin, adcMax, adcMax - adcMin);
    }

    delay(2000);
}
