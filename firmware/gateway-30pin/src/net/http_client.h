#pragma once
#include <stdint.h>
#include <stdbool.h>
#include "core/packet_buffer.h"

// =============================================================================
//  HTTP CLIENT - Gửi telemetry data lên Cloud Server
//  Format JSON theo API: POST /api/v1/telemetry
// =============================================================================

/**
 * Gửi batch gói tin lên server
 * Serialize BufferedPacket[] → JSON → HTTP POST
 *
 * @param packets  Mảng gói tin đã flush từ buffer
 * @param count    Số gói tin trong mảng
 * @return true nếu server trả về 200 OK
 */
bool http_sendBatch(const BufferedPacket* packets, uint8_t count);

/**
 * Gửi heartbeat lên server (không chứa sensor data)
 * POST /api/v1/telemetry/heartbeat
 *
 * @return true nếu server trả về 200 OK
 */
bool http_sendHeartbeat();
