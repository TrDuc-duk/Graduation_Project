/**
 * TEST: WiFi - Kết nối WiFi và hiển thị thông tin
 *
 * Flash: pio run -e test_wifi -t upload && pio device monitor
 *
 * PASS khi: Kết nối WiFi thành công, có IP address
 */

#include <Arduino.h>
#include <WiFi.h>
#include "config.h"

void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("========================================");
    Serial.println("  TEST: WiFi Connection");
    Serial.printf("  SSID: %s\n", WIFI_SSID);
    Serial.println("========================================");
    Serial.println();

    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    Serial.print("[WiFi] Đang kết nối");
    unsigned long start = millis();

    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - start > WIFI_CONNECT_TIMEOUT_MS) {
            Serial.println();
            Serial.println("[WiFi] ❌ TIMEOUT! Không kết nối được.");
            Serial.println("  → Kiểm tra SSID, password, router");
            Serial.println("  → Thử restart ESP32");
            while (true) delay(1000);
        }
        Serial.print(".");
        delay(500);
    }
    Serial.println();

    Serial.println("[WiFi] ✅ Kết nối thành công!");
    Serial.printf("  IP:   %s\n", WiFi.localIP().toString().c_str());
    Serial.printf("  RSSI: %d dBm\n", WiFi.RSSI());
    Serial.printf("  MAC:  %s\n", WiFi.macAddress().c_str());
    Serial.println();
    Serial.println("[WiFi] Theo dõi trạng thái mỗi 5 giây...");
    Serial.println("────────────────────────────────────────");
    Serial.println("  #  │  Status  │   RSSI   │ Kết quả");
    Serial.println("────────────────────────────────────────");
}

static uint16_t readCount = 0;

void loop() {
    readCount++;

    bool connected = (WiFi.status() == WL_CONNECTED);
    int rssi = WiFi.RSSI();

    const char* status  = connected ? "ONLINE " : "OFFLINE";
    const char* quality = (rssi > -50) ? "✅ Tốt" :
                          (rssi > -70) ? "✅ OK " :
                          (rssi > -80) ? "⚠ Yếu" : "❌ Kém";

    Serial.printf(" %3d │ %s │ %4d dBm │ %s\n",
                   readCount, status, rssi, connected ? quality : "❌ FAIL");

    delay(5000);
}
