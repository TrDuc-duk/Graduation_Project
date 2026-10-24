/**
 * TEST: HTTP POST - Gửi JSON giả lên Cloud Server
 *
 * Flash: pio run -e test_http -t upload && pio device monitor
 *
 * Cần: Server backend đang chạy ở API_URL
 * PASS khi: Server trả về 200 OK
 */

#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include "config.h"

static uint16_t sendCount = 0;

void setup()
{
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("========================================");
    Serial.println("  TEST: HTTP POST → Cloud Server");
    Serial.printf("  API: %s\n", API_URL);
    Serial.printf("  Gateway ID: %s\n", GATEWAY_ID);
    Serial.println("========================================");
    Serial.println();

    // Kết nối WiFi trước
    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.print("[WiFi] Đang kết nối");

    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED)
    {
        if (millis() - start > WIFI_CONNECT_TIMEOUT_MS)
        {
            Serial.println("\n[WiFi] ❌ Timeout! Không kết nối được.");
            while (true)
                delay(1000);
        }
        Serial.print(".");
        delay(500);
    }
    Serial.printf("\n[WiFi] ✅ IP: %s\n\n", WiFi.localIP().toString().c_str());

    Serial.println("[HTTP] Gửi JSON test mỗi 10 giây...");
    Serial.println("────────────────────────────────────────");
}

void loop()
{
    if (WiFi.status() != WL_CONNECTED)
    {
        Serial.println("[WiFi] ⚠ Mất kết nối!");
        delay(5000);
        return;
    }

    sendCount++;

    // Tạo JSON giả giống đúng format backend expect
    JsonDocument doc;
    doc["gateway_id"] = GATEWAY_ID;
    doc["secret"] = GATEWAY_SECRET;

    JsonArray dataArray = doc["data"].to<JsonArray>();
    JsonObject item = dataArray.add<JsonObject>();

    item["node_id"] = "NODE_001";
    item["pm25"] = 12.3 + (sendCount % 10) * 0.5;
    item["pm10"] = 45.6;
    item["co2"] = 800 + sendCount;
    item["tvoc"] = 50;
    item["temperature"] = 27.5;
    item["humidity"] = 65.0;
    item["battery"] = 85;
    item["rssi"] = -67;

    String jsonPayload;
    serializeJson(doc, jsonPayload);

    Serial.printf("[HTTP] #%d Gửi %d bytes...\n", sendCount, jsonPayload.length());

    HTTPClient http;
    http.begin(API_URL);
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(API_TIMEOUT_MS);

    unsigned long txStart = millis();
    int httpCode = http.POST(jsonPayload);
    unsigned long txTime = millis() - txStart;

    if (httpCode == 200)
    {
        String response = http.getString();
        Serial.printf("[HTTP] ✅ 200 OK (%lu ms)\n", txTime);
        Serial.printf("[HTTP]    Response: %s\n", response.c_str());
    }
    else if (httpCode > 0)
    {
        String response = http.getString();
        Serial.printf("[HTTP] ❌ HTTP %d (%lu ms)\n", httpCode, txTime);
        Serial.printf("[HTTP]    Response: %s\n", response.c_str());
    }
    else
    {
        Serial.printf("[HTTP] ❌ Connection failed: %s (%lu ms)\n",
                      http.errorToString(httpCode).c_str(), txTime);
    }

    http.end();
    Serial.println();

    delay(10000);
}
