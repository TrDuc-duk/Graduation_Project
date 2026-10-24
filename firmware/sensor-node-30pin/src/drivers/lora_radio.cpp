#include "lora_radio.h"
#include <Arduino.h>
#include "config.h"
#include "common/debug.h"

// =============================================================================
//  AS32-TTL-100 LORA DRIVER IMPLEMENTATION (30-pin board)
//  Giao tiếp: UART transparent (ghi binary → module phát LoRa)
//  Mode: MD0/MD1 điều khiển chế độ
//  Board 30 chân: Không có AUX pin → dùng delay thay thế
// =============================================================================

static HardwareSerial loraSerial(LORA_UART_NUM);

// ───── Helper: Đổi mode MD0/MD1 ─────
static void setMode(uint8_t md0, uint8_t md1) {
    digitalWrite(LORA_MD0_PIN, md0);
    digitalWrite(LORA_MD1_PIN, md1);
    delay(100);  // Chờ module ổn định (không có AUX nên dùng delay)
}

bool lora_init() {
    // Cấu hình chân điều khiển
    pinMode(LORA_MD0_PIN, OUTPUT);
    pinMode(LORA_MD1_PIN, OUTPUT);

    // Khởi tạo UART
    loraSerial.begin(LORA_BAUD, SERIAL_8N1, LORA_RX_PIN, LORA_TX_PIN);

    // Đặt Normal mode (MD0=0, MD1=0) — transparent transmission
    setMode(LOW, LOW);

    // Chờ module khởi động (board 30 chân không có AUX pin)
    delay(1000);

    // Flush bất kỳ data rác nào trong buffer
    while (loraSerial.available()) loraSerial.read();

    LOG_MSG("LoRa", "Khởi tạo... OK! (AS32-TTL-100, UART)");
    LOG_INFO("LoRa", "  UART: Serial%d (RX=%d, TX=%d, %d baud)",
                LORA_UART_NUM, LORA_RX_PIN, LORA_TX_PIN, LORA_BAUD);
    LOG_INFO("LoRa", "  Mode: Normal (MD0=%d, MD1=%d)",
                LORA_MD0_PIN, LORA_MD1_PIN);

    return true;
}

bool lora_sendPacket(const SensorPayload* payload) {
    // Đảm bảo đang ở Normal mode
    lora_wakeup();

    // Board 30 chân không có AUX → delay chờ module sẵn sàng
    delay(50);

    // Gửi 18 bytes binary qua UART → module tự phát LoRa
    size_t written = loraSerial.write((const uint8_t*)payload, sizeof(SensorPayload));

    // Chờ module gửi xong (không có AUX → delay)
    delay(200);

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
