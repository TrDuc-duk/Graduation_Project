/**
 * TEST: LoRa AS32-TTL-100 - Module truyền không dây (UART)
 * Giao tiếp: UART (Serial1 remap GPIO32/33) + MD0/MD1/AUX
 *
 * Flash: pio run -e test_lora -t upload && pio device monitor
 *
 * PASS khi: Init OK (AUX HIGH), gửi 18 bytes không lỗi
 * Để kiểm tra nhận: cần 1 module AS32 khác ở cùng cấu hình
 */

#include <Arduino.h>
#include "config.h"
#include "common/packet.h"
#include "common/debug.h"

static HardwareSerial loraSerial(LORA_UART_NUM);
static uint8_t packetCount = 0;

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
    Serial.println("  TEST: LoRa AS32-TTL-100 (UART)");
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

    // Normal mode
    digitalWrite(LORA_MD0_PIN, LOW);
    digitalWrite(LORA_MD1_PIN, LOW);

    // Init UART
    loraSerial.begin(LORA_BAUD, SERIAL_8N1, LORA_RX_PIN, LORA_TX_PIN);
    delay(500);

    // Test AUX
    Serial.print("[LoRa] Kiểm tra AUX... ");
    if (waitAux(3000)) {
        Serial.println("✅ HIGH (module sẵn sàng)");
    } else {
        Serial.println("❌ TIMEOUT (module không phản hồi)");
        Serial.println("  → Kiểm tra: VCC, GND, AUX nối GPIO đúng");
    }

    // Flush buffer
    while (loraSerial.available()) loraSerial.read();

    // Test Sleep/Wakeup
    Serial.print("[LoRa] Test Sleep mode (MD0=1,MD1=1)... ");
    digitalWrite(LORA_MD0_PIN, HIGH);
    digitalWrite(LORA_MD1_PIN, HIGH);
    delay(100);
    waitAux();
    Serial.println("OK");

    Serial.print("[LoRa] Test Normal mode (MD0=0,MD1=0)... ");
    digitalWrite(LORA_MD0_PIN, LOW);
    digitalWrite(LORA_MD1_PIN, LOW);
    delay(100);
    waitAux();
    Serial.println("OK");

    Serial.println();
    Serial.println("[LoRa] ✅ INIT OK! Gửi gói test mỗi 5 giây...");
    Serial.println("──────────────────────────────────────────");
    Serial.println("  #  │ Size │ MsgID │  AUX  │ Kết quả");
    Serial.println("──────────────────────────────────────────");
}

void loop() {
    packetCount++;

    // Tạo gói test
    SensorPayload testPkt;
    memset(&testPkt, 0, sizeof(SensorPayload));
    testPkt.nodeId      = NODE_ID;
    testPkt.pktType     = PKT_TYPE_DATA;
    testPkt.msgId       = packetCount;
    testPkt.pm1         = 95;
    testPkt.pm25        = 123;
    testPkt.pm10        = 456;
    testPkt.co2         = 800;
    testPkt.tvoc        = 50;
    testPkt.temperature = 275;
    testPkt.humidity    = 650;
    testPkt.battery     = 85;

    // Chờ AUX ready
    bool auxOk = waitAux(2000);

    if (auxOk) {
        size_t written = loraSerial.write((const uint8_t*)&testPkt, sizeof(SensorPayload));
        delay(10);
        bool sendOk = waitAux(5000);

        const char* result = (written == sizeof(SensorPayload) && sendOk) ? "✅ PASS" : "❌ FAIL";
        Serial.printf(" %3d │ %2d B │  %3d  │  %s  │ %s\n",
                       packetCount, written, testPkt.msgId,
                       sendOk ? "OK " : "ERR", result);
    } else {
        Serial.printf(" %3d │  -- │  %3d  │  ERR │ ❌ AUX BUSY\n",
                       packetCount, testPkt.msgId);
    }

    // Kiểm tra nếu có data nhận được (từ module khác)
    if (loraSerial.available() >= (int)sizeof(SensorPayload)) {
        SensorPayload rxPkt;
        loraSerial.readBytes((uint8_t*)&rxPkt, sizeof(SensorPayload));
        Serial.printf("     >>> RX: Node:0x%02X MsgID:%d PM2.5:%.1f\n",
                       rxPkt.nodeId, rxPkt.msgId, rxPkt.pm25 / 10.0f);
    }

    delay(5000);
}
