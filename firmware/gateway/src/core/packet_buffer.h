#pragma once
#include <stdbool.h>
#include "common/packet.h"

// =============================================================================
//  PACKET BUFFER - Ring buffer ISR-safe cho gói LoRa chờ gửi HTTP
// =============================================================================

typedef struct {
    SensorPayload payload;
    int16_t       rssi;         // LoRa RSSI (dBm)
    uint32_t      receivedAt;   // millis() khi nhận
} BufferedPacket;

/**
 * Khởi tạo buffer (reset về rỗng)
 */
void buffer_init();

/**
 * Thêm gói tin vào buffer (gọi từ ISR callback — phải nhanh)
 * @return true nếu thêm được, false nếu buffer đầy
 */
bool buffer_push(const SensorPayload* payload, int16_t rssi);

/**
 * Lấy tất cả gói tin ra khỏi buffer
 * @param outArray Mảng output (caller cấp phát)
 * @param maxCount Kích thước mảng output
 * @return Số gói đã lấy ra
 */
uint8_t buffer_flush(BufferedPacket* outArray, uint8_t maxCount);

/**
 * Số gói hiện có trong buffer
 */
uint8_t buffer_count();

/**
 * Kiểm tra buffer đầy
 */
bool buffer_isFull();
