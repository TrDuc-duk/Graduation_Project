#include "lora_receiver.h"
#include <Arduino.h>
#include "config.h"
#include "common/debug.h"
#include "common/packet.h"
#include "core/packet_buffer.h"
#include "drivers/oled_display.h"

// =============================================================================
//  LORA RECEIVER IMPLEMENTATION (AS32-TTL-100 UART)
//  Nhận gói tin 18 bytes (SensorPayload) từ Sensor Node
//  Module AS32 nhận RF → giải điều chế → đẩy data ra UART TX → ESP32 đọc
//
//  Cơ chế: poll UART trong loop(), không dùng interrupt callback
//  (AS32 là transparent serial bridge, data đến qua UART bình thường)
// =============================================================================

static HardwareSerial loraSerial(LORA_UART_NUM);
static uint32_t rxPacketCount = 0;
static uint32_t rxErrorCount = 0;

// Timeout nhận: nếu đã nhận 1+ byte nhưng chưa đủ 18 byte trong 1 giây → reset
static uint8_t rxBuffer[sizeof(SensorPayload)];
static uint8_t rxIndex = 0;
static uint32_t rxStartTime = 0;
#define RX_TIMEOUT_MS 1000



bool lora_rx_init()
{
    // Cấu hình chân điều khiển
    pinMode(LORA_MD0_PIN, OUTPUT);
    pinMode(LORA_MD1_PIN, OUTPUT);

    // Init UART
    loraSerial.begin(LORA_BAUD, SERIAL_8N1, LORA_RX_PIN, LORA_TX_PIN);

    // Normal mode (MD0=0, MD1=0) — transparent receive
    digitalWrite(LORA_MD0_PIN, LOW);
    digitalWrite(LORA_MD1_PIN, LOW);
    delay(100);

    // Chờ module khởi động (board 30 chân không có AUX pin)
    delay(1000);

    // Flush buffer
    while (loraSerial.available())
        loraSerial.read();
    rxIndex = 0;

    LOG_MSG("LoRa RX", "Khởi tạo OK! (AS32-TTL-100, UART)");
    LOG_INFO("LoRa RX", "  UART: Serial%d (RX=%d, TX=%d, %d baud)",
             LORA_UART_NUM, LORA_RX_PIN, LORA_TX_PIN, LORA_BAUD);
    LOG_MSG("LoRa RX", "Đang lắng nghe gói tin LoRa...");

    return true;
}

void lora_rx_poll()
{
    // Đọc từng byte từ UART vào rxBuffer
    while (loraSerial.available())
    {
        uint8_t b = loraSerial.read();

        if (rxIndex == 0)
        {
            rxStartTime = millis(); // Bắt đầu nhận gói mới
        }

        rxBuffer[rxIndex++] = b;

        // Đã nhận đủ 1 gói SensorPayload
        if (rxIndex >= sizeof(SensorPayload))
        {
            SensorPayload payload;
            memcpy(&payload, rxBuffer, sizeof(SensorPayload));
            rxIndex = 0;

            // Validate cơ bản: nodeId != 0, pktType hợp lệ
            if (payload.nodeId == 0 || payload.pktType > PKT_TYPE_ERROR)
            {
                rxErrorCount++;
                LOG_INFO("LoRa RX", "⚠ Gói không hợp lệ (nodeId=%d, pktType=0x%02X)",
                         payload.nodeId, payload.pktType);
                continue;
            }

            // AS32 không cung cấp RSSI qua UART → gửi 0 (unknown)
            buffer_push(&payload, 0);
            rxPacketCount++;
            oled_setLastPacket(payload.nodeId, payload.pktType);

            const char *typeStr = (payload.pktType == PKT_TYPE_DATA) ? "DATA" : (payload.pktType == PKT_TYPE_HEARTBEAT) ? "HB"
                                                                                                                        : "ERR";

            LOG_INFO("LoRa RX", "Nhận gói #%d: Node:0x%02X Type:%s MsgID:%d",
                     rxPacketCount, payload.nodeId, typeStr, payload.msgId);
        }
    }

    // Timeout: nếu đã bắt đầu nhận nhưng chưa đủ 18 bytes quá lâu → reset
    if (rxIndex > 0 && (millis() - rxStartTime) > RX_TIMEOUT_MS)
    {
        LOG_INFO("LoRa RX", "⚠ RX timeout (%d/%d bytes), reset buffer.",
                 rxIndex, sizeof(SensorPayload));
        rxIndex = 0;
        rxErrorCount++;
    }
}

uint32_t lora_rx_getPacketCount()
{
    return rxPacketCount;
}

uint32_t lora_rx_getErrorCount()
{
    return rxErrorCount;
}
