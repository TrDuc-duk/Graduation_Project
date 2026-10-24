#pragma once
#include <stdint.h>

// =============================================================================
//  LoRa PACKET DEFINITION
//  Cấu trúc gói tin LoRa - Dùng chung cho Sensor Node & Gateway
//  Tổng kích thước: 18 bytes
// =============================================================================

// --- Packet Types ---
#define PKT_TYPE_DATA       0x01    // Gói dữ liệu cảm biến
#define PKT_TYPE_HEARTBEAT  0x02    // Gói heartbeat (node còn sống)
#define PKT_TYPE_ERROR      0x03    // Gói báo lỗi sensor

// --- Sentinel Values (báo sensor lỗi) ---
#define SENSOR_ERROR_U16    0xFFFF  // Giá trị lỗi cho uint16_t
#define SENSOR_ERROR_I16    0x7FFF  // Giá trị lỗi cho int16_t

// --- Sensor Payload Struct ---
typedef struct __attribute__((packed)) {
    uint8_t  nodeId;        // 1 byte  - ID node (1-255)
    uint8_t  pktType;       // 1 byte  - Loại gói tin (PKT_TYPE_*)
    uint8_t  msgId;         // 1 byte  - Bộ đếm gói tin (0-255, wrap-around)
    uint16_t pm1;           // 2 bytes - PM1   (µg/m³ × 10)
    uint16_t pm25;          // 2 bytes - PM2.5 (µg/m³ × 10)
    uint16_t pm10;          // 2 bytes - PM10  (µg/m³ × 10)
    uint16_t co2;           // 2 bytes - CO2   (ppm)
    uint16_t tvoc;          // 2 bytes - TVOC  (ppb)
    int16_t  temperature;   // 2 bytes - Nhiệt độ (°C × 10), có dấu cho nhiệt độ âm
    uint16_t humidity;      // 2 bytes - Độ ẩm (% × 10)
    uint8_t  battery;       // 1 byte  - Pin  (0-100%)
} SensorPayload;            // Tổng: 18 bytes
