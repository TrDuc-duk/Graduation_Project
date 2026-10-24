#include "packet_buffer.h"
#include <Arduino.h>
#include "config.h"
#include "common/debug.h"

// =============================================================================
//  PACKET BUFFER IMPLEMENTATION
//  Ring buffer đơn giản, ISR-safe bằng portENTER_CRITICAL
//  (ESP32 Arduino Core đã cung cấp spinlock)
// =============================================================================

static BufferedPacket ringBuffer[PACKET_BUFFER_SIZE];
static volatile uint8_t head = 0;     // Vị trí ghi tiếp theo
static volatile uint8_t count = 0;    // Số phần tử hiện có

static portMUX_TYPE bufferMux = portMUX_INITIALIZER_UNLOCKED;

void buffer_init() {
    portENTER_CRITICAL(&bufferMux);
    head = 0;
    count = 0;
    memset(ringBuffer, 0, sizeof(ringBuffer));
    portEXIT_CRITICAL(&bufferMux);

    LOG_MSG("BUFFER", "Khởi tạo OK");
}

bool buffer_push(const SensorPayload* payload, int16_t rssi) {
    portENTER_CRITICAL(&bufferMux);

    if (count >= PACKET_BUFFER_SIZE) {
        portEXIT_CRITICAL(&bufferMux);
        LOG_MSG("BUFFER", "⚠ Buffer đầy! Bỏ gói tin.");
        return false;
    }

    uint8_t idx = (head + count) % PACKET_BUFFER_SIZE;
    ringBuffer[idx].payload    = *payload;
    ringBuffer[idx].rssi       = rssi;
    ringBuffer[idx].receivedAt = millis();
    count++;

    portEXIT_CRITICAL(&bufferMux);
    return true;
}

uint8_t buffer_flush(BufferedPacket* outArray, uint8_t maxCount) {
    portENTER_CRITICAL(&bufferMux);

    uint8_t toFlush = (count < maxCount) ? count : maxCount;

    for (uint8_t i = 0; i < toFlush; i++) {
        uint8_t idx = (head + i) % PACKET_BUFFER_SIZE;
        outArray[i] = ringBuffer[idx];
    }

    head = (head + toFlush) % PACKET_BUFFER_SIZE;
    count -= toFlush;

    portEXIT_CRITICAL(&bufferMux);
    return toFlush;
}

uint8_t buffer_count() {
    portENTER_CRITICAL(&bufferMux);
    uint8_t c = count;
    portEXIT_CRITICAL(&bufferMux);
    return c;
}

bool buffer_isFull() {
    return buffer_count() >= PACKET_BUFFER_SIZE;
}
