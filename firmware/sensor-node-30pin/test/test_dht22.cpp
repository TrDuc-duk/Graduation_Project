/**
 * TEST: DHT22 - Cảm biến nhiệt độ / độ ẩm
 * Giao tiếp: 1-Wire (GPIO4)
 * 
 * Flash: pio run -e test_dht22 -t upload && pio device monitor
 * 
 * PASS khi: Đọc được nhiệt độ 15~45°C, độ ẩm 20~90% (trong phòng)
 */

#include <Arduino.h>
#include <DHT.h>
#include "config.h"

static DHT dht(DHT_PIN, DHT_TYPE);

void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("========================================");
    Serial.println("  TEST: DHT22 (Nhiệt độ / Độ ẩm)");
    Serial.printf("  Data Pin: GPIO%d\n", DHT_PIN);
    Serial.println("========================================");
    Serial.println();

    Serial.println("[DHT22] Khởi tạo...");
    dht.begin();
    delay(2000);  // DHT22 cần 2s sau khi bật nguồn

    // Test đọc lần đầu
    float t = dht.readTemperature();
    if (isnan(t)) {
        Serial.println("[DHT22] ❌ INIT FAIL - Không đọc được dữ liệu!");
        Serial.println("  → Kiểm tra: dây nối GPIO4, pull-up 10K, nguồn 3.3V");
    } else {
        Serial.printf("[DHT22] ✅ INIT OK - Đọc thử: %.1f°C\n", t);
    }

    Serial.println();
    Serial.println("[DHT22] Bắt đầu đọc liên tục mỗi 3 giây...");
    Serial.println("─────────────────────────────────────────");
    Serial.println("  #  │ Nhiệt độ │  Độ ẩm  │    Raw    │ Kết quả");
    Serial.println("─────────────────────────────────────────");
}

static uint16_t readCount = 0;

void loop() {
    readCount++;

    float temp = dht.readTemperature();
    float hum  = dht.readHumidity();

    if (!isnan(temp) && !isnan(hum)) {
        // Chuyển sang giá trị ×10 như firmware chính
        int16_t  rawT = (int16_t)(temp * 10.0f);
        uint16_t rawH = (uint16_t)(hum * 10.0f);

        // Kiểm tra dải hợp lệ (trong phòng)
        bool tempOk = (temp >= -40.0f && temp <= 80.0f);
        bool humOk  = (hum >= 0.0f && hum <= 100.0f);
        const char* status = (tempOk && humOk) ? "✅ PASS" : "⚠ RANGE";

        Serial.printf(" %3d │ %5.1f°C  │ %5.1f%%  │ T:%d H:%d │ %s\n",
                       readCount, temp, hum, rawT, rawH, status);
    } else {
        Serial.printf(" %3d │  ERROR   │  ERROR  │    ---    │ ❌ FAIL\n", readCount);
    }

    delay(3000);  // DHT22 cần tối thiểu 2s giữa các lần đọc
}
