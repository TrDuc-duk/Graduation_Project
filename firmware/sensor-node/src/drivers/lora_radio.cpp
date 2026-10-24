#include "lora_radio.h"
#include <Arduino.h>
#include "config.h"
#include "common/debug.h"

// =============================================================================
//  AS32-TTL-100 LORA DRIVER IMPLEMENTATION
//  Giao tiếp: UART transparent (ghi binary → module phát LoRa)
//  Mode: MD0/MD1 điều khiển chế độ, AUX báo trạng thái busy/ready
//
//  Normal mode (MD0=0, MD1=0): UART ↔ LoRa transparent transmission
//  Sleep mode  (MD0=1, MD1=1): Cấu hình module / tiết kiệm pin
// =============================================================================

static HardwareSerial loraSerial(LORA_UART_NUM);

// ───── Helper: Chờ AUX HIGH (module sẵn sàng) ─────
static bool waitAuxReady(uint32_t timeoutMs = 2000) {
    uint32_t start = millis();
    while (digitalRead(LORA_AUX_PIN) == LOW) {
        if (millis() - start > timeoutMs) {
            LOG_MSG("LoRa", "⚠ AUX timeout!");
            return false;
        }
        delay(1);
    }
    return true;
}

// ───── Helper: Đổi mode MD0/MD1 ─────
static void setMode(uint8_t md0, uint8_t md1) {
    digitalWrite(LORA_MD0_PIN, md0);
    digitalWrite(LORA_MD1_PIN, md1);
    delay(50);          // Module cần thời gian chuyển mode
    waitAuxReady();     // Chờ module ổn định
}

bool lora_init() {
    // Cấu hình chân điều khiển
    pinMode(LORA_MD0_PIN, OUTPUT);
    pinMode(LORA_MD1_PIN, OUTPUT);
    pinMode(LORA_AUX_PIN, INPUT);

    // Khởi tạo UART (Serial1 remap sang GPIO32/33)
    loraSerial.begin(LORA_BAUD, SERIAL_8N1, LORA_RX_PIN, LORA_TX_PIN);

    // Đặt Normal mode (MD0=0, MD1=0) — transparent transmission
    setMode(LOW, LOW);

    // Chờ module khởi động (AUX LOW → HIGH)
    delay(500);
    if (!waitAuxReady(3000)) {
        LOG_MSG("LoRa", "THẤT BẠI! Module không phản hồi (AUX timeout).");
        return false;
    }

    // Flush bất kỳ data rác nào trong buffer
    while (loraSerial.available()) loraSerial.read();

    LOG_MSG("LoRa", "Khởi tạo... OK! (AS32-TTL-100, UART)");
    LOG_INFO("LoRa", "  UART: Serial%d (RX=%d, TX=%d, %d baud)",
                LORA_UART_NUM, LORA_RX_PIN, LORA_TX_PIN, LORA_BAUD);
    LOG_INFO("LoRa", "  Mode: Normal (MD0=%d, MD1=%d), AUX=%d",
                LORA_MD0_PIN, LORA_MD1_PIN, LORA_AUX_PIN);

    return true;
}

bool lora_sendPacket(const SensorPayload* payload) {
    // Đảm bảo đang ở Normal mode
    lora_wakeup();

    // Chờ module sẵn sàng
    if (!waitAuxReady(2000)) {
        LOG_MSG("LoRa", "Gửi THẤT BẠI! Module bận (AUX LOW).");
        return false;
    }

    // Gửi 18 bytes binary qua UART → module tự phát LoRa
    size_t written = loraSerial.write((const uint8_t*)payload, sizeof(SensorPayload));

    // Chờ module gửi xong (AUX LOW → HIGH)
    delay(10);  // Nhỏ delay để AUX kịp kéo LOW
    if (!waitAuxReady(5000)) {
        LOG_MSG("LoRa", "⚠ Gửi timeout (AUX không lên HIGH).");
        return false;
    }

    if (written == sizeof(SensorPayload)) {
        LOG_INFO("LoRa", "Đã gửi %d bytes (MsgID: %d, PktType: 0x%02X)",
                    sizeof(SensorPayload), payload->msgId, payload->pktType);
        return true;
    } else {
        LOG_INFO("LoRa", "Gửi THẤT BẠI! Chỉ ghi được %d/%d bytes.",
                    written, sizeof(SensorPayload));
        return false;
    }
}

void lora_sleep() {
    setMode(HIGH, HIGH);    // Sleep mode (MD0=1, MD1=1)
    LOG_MSG("LoRa", "Module sleep");
}

void lora_wakeup() {
    setMode(LOW, LOW);      // Normal mode (MD0=0, MD1=0)
}
