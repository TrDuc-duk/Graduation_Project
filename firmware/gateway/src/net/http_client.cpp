#include "http_client.h"
#include <Arduino.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>
#include "config.h"
#include "common/debug.h"
#include "common/packet.h"
#include "core/nvs_config.h"

// =============================================================================
//  HTTP CLIENT IMPLEMENTATION
//  Serialize BufferedPacket[] → JSON → HTTP POST đến Cloud Server
//
//  Dùng biến runtime từ NVS: cfg_gatewayId, cfg_apiUrl
//
//  JSON format (khớp với gatewayValidation.js + telemetryService.js):
//  {
//    "gateway_id": "GW_001",
//    "data": [
//      {
//        "node_id": "NODE_001",
//        "pm25": 70.0, "pm10": 60.0,
//        "co2": 800, "tvoc": 120,
//        "temperature": 32.5, "humidity": 70,
//        "battery": 92, "rssi": -65
//      }
//    ]
//  }
// =============================================================================

bool http_sendBatch(const BufferedPacket* packets, uint8_t count) {
    if (count == 0) return true;

    // Tạo JSON document
    // Ước tính kích thước: ~200 bytes/packet + overhead
    JsonDocument doc;

    doc["gateway_id"] = cfg_gatewayId;
    doc["secret"]     = GATEWAY_SECRET;
    JsonArray dataArray = doc["data"].to<JsonArray>();

    for (uint8_t i = 0; i < count; i++) {
        const SensorPayload* p = &packets[i].payload;
        JsonObject item = dataArray.add<JsonObject>();

        // Node ID format: "NODE_001"
        char nodeIdStr[16];
        snprintf(nodeIdStr, sizeof(nodeIdStr), "NODE_%03d", p->nodeId);
        item["node_id"] = nodeIdStr;
        item["msg_id"]  = p->msgId;    // Server dùng để dedup khi nhiều GW nhận cùng 1 gói

        // Chuyển đổi scaled values → float (÷10)
        // Nếu sensor lỗi (SENSOR_ERROR) → gửi null
        if (p->pm25 != SENSOR_ERROR_U16)
            item["pm25"] = p->pm25 / 10.0f;
        else
            item["pm25"] = (char*)NULL;

        if (p->pm10 != SENSOR_ERROR_U16)
            item["pm10"] = p->pm10 / 10.0f;
        else
            item["pm10"] = (char*)NULL;

        item["co2"]  = p->co2;
        item["tvoc"] = p->tvoc;

        if (p->temperature != SENSOR_ERROR_I16)
            item["temperature"] = p->temperature / 10.0f;
        else
            item["temperature"] = (char*)NULL;

        if (p->humidity != SENSOR_ERROR_U16)
            item["humidity"] = p->humidity / 10.0f;
        else
            item["humidity"] = (char*)NULL;

        item["battery"] = p->battery;
        item["rssi"]    = packets[i].rssi;
    }

    // Serialize JSON → String
    String jsonPayload;
    serializeJson(doc, jsonPayload);

    LOG_INFO("HTTP", "Gửi %d gói tin (%d bytes JSON)", count, jsonPayload.length());

    // Gửi HTTP POST với retry
    HTTPClient http;
    WiFiClientSecure client;
    client.setInsecure(); // Skip cert verify (IoT device, không cần pin cert)
    bool success = false;

    for (int attempt = 1; attempt <= HTTP_RETRY_COUNT; attempt++) {
        http.begin(client, cfg_apiUrl);
        http.addHeader("Content-Type", "application/json");
        http.setTimeout(API_TIMEOUT_MS);

        int httpCode = http.POST(jsonPayload);

        if (httpCode == 200) {
            String response = http.getString();
            LOG_INFO("HTTP", "✅ Gửi OK! Server: %s", response.c_str());
            success = true;
            http.end();
            break;
        } else {
            LOG_INFO("HTTP", "❌ Lỗi %d (lần %d/%d)", httpCode, attempt, HTTP_RETRY_COUNT);
            if (httpCode > 0) {
                String response = http.getString();
                LOG_INFO("HTTP", "  Response: %s", response.c_str());
            }
            http.end();

            if (attempt < HTTP_RETRY_COUNT) {
                delay(1000 * attempt);  // Exponential-ish backoff
            }
        }
    }

    if (!success) {
        LOG_INFO("HTTP", "🔴 Gửi THẤT BẠI sau %d lần thử!", HTTP_RETRY_COUNT);
    }

    return success;
}

bool http_sendHeartbeat() {
    // Construct heartbeat URL from base URL
    char heartbeatUrl[192];
    snprintf(heartbeatUrl, sizeof(heartbeatUrl), "%s/api/v1/telemetry/heartbeat", cfg_serverBase);

    // Minimal JSON payload
    JsonDocument doc;
    doc["gateway_id"] = cfg_gatewayId;
    doc["secret"]     = GATEWAY_SECRET;

    String jsonPayload;
    serializeJson(doc, jsonPayload);

    LOG_INFO("HTTP", "Heartbeat → %s", heartbeatUrl);

    HTTPClient http;
    WiFiClientSecure client;
    client.setInsecure();

    http.begin(client, heartbeatUrl);
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(API_TIMEOUT_MS);

    int httpCode = http.POST(jsonPayload);
    http.end();

    if (httpCode == 200) {
        LOG_INFO("HTTP", "✅ Heartbeat OK");
        return true;
    } else {
        LOG_INFO("HTTP", "❌ Heartbeat lỗi %d", httpCode);
        return false;
    }
}
