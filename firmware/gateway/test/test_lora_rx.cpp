/**
 * TEST: LoRa RX - Nhận gói tin từ Sensor Node (AS32-TTL-100 UART)
 *
 * Flash: pio run -e test_lora_rx -t upload && pio device monitor
 *
 * Cần: 1 sensor node đang chạy và gửi gói tin LoRa
 * PASS khi: Nhận được gói 18 bytes, parse đúng SensorPayload
 */

#include <Arduino.h>
#include "config.h"
#include "common/packet.h"

static HardwareSerial loraSerial(LORA_UART_NUM);
static uint32_t rxCount = 0;
static uint32_t errCount = 0;

// RX buffer
static uint8_t rxBuffer[sizeof(SensorPayload)];
static uint8_t rxIndex = 0;
static uint32_t rxStartTime = 0;

// Chờ AUX HIGH
bool waitAux(uint32_t timeoutMs = 2000) {
    uint32_t start = millis();
    while (digitalRead(LORA_AUX_PIN) == LOW) {
        if (millis() - start > timeoutMs) return false;
        delay(1);
    }
    return true;
}

void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("========================================");
    Serial.println("  TEST: LoRa RX (AS32-TTL-100 UART)");
    Serial.printf("  UART: Serial%d (RX=%d, TX=%d, %d baud)\n",
                  LORA_UART_NUM, LORA_RX_PIN, LORA_TX_PIN, LORA_BAUD);
    Serial.printf("  MD0=%d, MD1=%d, AUX=%d\n",
                  LORA_MD0_PIN, LORA_MD1_PIN, LORA_AUX_PIN);
    Serial.println("========================================");
    Serial.println();

    // Init pins
    pinMode(LORA_MD0_PIN, OUTPUT);
    pinMode(LORA_MD1_PIN, OUTPUT);
    pinMode(LORA_AUX_PIN, INPUT);

    // Normal mode (nhận)
    digitalWrite(LORA_MD0_PIN, LOW);
    digitalWrite(LORA_MD1_PIN, LOW);

    // Init UART
    loraSerial.begin(LORA_BAUD, SERIAL_8N1, LORA_RX_PIN, LORA_TX_PIN);
    delay(500);

    // Kiểm tra AUX
    if (waitAux(3000)) {
        Serial.println("[LoRa RX] ✅ Module sẵn sàng (AUX HIGH)");
    } else {
        Serial.println("[LoRa RX] ❌ Module không phản hồi (AUX timeout)");
    }

    // Flush
    while (loraSerial.available()) loraSerial.read();

    Serial.println();
    Serial.println("[LoRa RX] Đang lắng nghe gói tin từ Sensor Node...");
    Serial.println();
}

void loop() {
    // Đọc byte từ UART
    while (loraSerial.available()) {
        uint8_t b = loraSerial.read();

        if (rxIndex == 0) {
            rxStartTime = millis();
        }
        rxBuffer[rxIndex++] = b;

        // Đủ 1 gói SensorPayload
        if (rxIndex >= sizeof(SensorPayload)) {
            SensorPayload payload;
            memcpy(&payload, rxBuffer, sizeof(SensorPayload));
            rxIndex = 0;

            // Validate
            if (payload.nodeId == 0 || payload.pktType > PKT_TYPE_ERROR) {
                errCount++;
                Serial.printf("[LoRa RX] ⚠ Gói không hợp lệ (node=%d, type=0x%02X)\n",
                               payload.nodeId, payload.pktType);
                continue;
            }

            rxCount++;

            // In chi tiết
            Serial.println("════════════════════════════════════════");
            Serial.printf("  GÓI #%d (Total: %d rx, %d err)\n", rxCount, rxCount, errCount);
            Serial.println("════════════════════════════════════════");

            const char* typeStr = (payload.pktType == PKT_TYPE_DATA) ? "DATA" :
                                  (payload.pktType == PKT_TYPE_HEARTBEAT) ? "HEARTBEAT" : "ERROR";

            Serial.printf("  Node ID  : 0x%02X\n", payload.nodeId);
            Serial.printf("  Pkt Type : 0x%02X (%s)\n", payload.pktType, typeStr);
            Serial.printf("  Msg ID   : %d\n", payload.msgId);

            if (payload.pktType == PKT_TYPE_DATA) {
                Serial.printf("  PM1.0    : %s\n",
                    payload.pm1 == SENSOR_ERROR_U16 ? "ERROR" :
                    String(payload.pm1 / 10.0f, 1).c_str());
                Serial.printf("  PM2.5    : %s\n",
                    payload.pm25 == SENSOR_ERROR_U16 ? "ERROR" :
                    String(payload.pm25 / 10.0f, 1).c_str());
                Serial.printf("  PM10     : %s\n",
                    payload.pm10 == SENSOR_ERROR_U16 ? "ERROR" :
                    String(payload.pm10 / 10.0f, 1).c_str());
                Serial.printf("  CO2      : %d ppm\n", payload.co2);
                Serial.printf("  TVOC     : %d ppb\n", payload.tvoc);
                Serial.printf("  Temp     : %s\n",
                    payload.temperature == SENSOR_ERROR_I16 ? "ERROR" :
                    String(payload.temperature / 10.0f, 1).c_str());
                Serial.printf("  Humidity : %s\n",
                    payload.humidity == SENSOR_ERROR_U16 ? "ERROR" :
                    String(payload.humidity / 10.0f, 1).c_str());
            }

            Serial.printf("  Battery  : %d%%\n", payload.battery);
            Serial.printf("  ✅ PASS\n");
            Serial.println();
        }
    }

    // RX timeout
    if (rxIndex > 0 && (millis() - rxStartTime) > 1000) {
        Serial.printf("[LoRa RX] ⚠ Timeout (%d/%d bytes), reset.\n",
                       rxIndex, sizeof(SensorPayload));
        rxIndex = 0;
        errCount++;
    }

    delay(10);
}
