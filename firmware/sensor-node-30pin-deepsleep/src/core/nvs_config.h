#pragma once
#include <stdbool.h>
#include <stdint.h>

// =============================================================================
//  NVS CONFIG — Sensor Node
//  Lưu/đọc cấu hình từ Non-Volatile Storage (ESP32 Preferences)
// =============================================================================

// ===== Runtime Config Variables =====
extern uint8_t  cfg_nodeId;          // Numeric ID cho SensorPayload (1-255)
extern char     cfg_nodeIdStr[16];   // String ID (VD: "NODE_004")
extern char     cfg_gatewayId[16];   // Gateway mà node thuộc về

/**
 * Đọc cấu hình từ NVS vào biến runtime
 */
void nvs_loadConfig();

/**
 * Kiểm tra đã cấu hình chưa
 * @return true nếu có node_id trong NVS
 */
bool nvs_isProvisioned();

/**
 * Lưu cấu hình sensor node vào NVS
 * @param nodeId    Numeric ID (1-255)
 * @param nodeIdStr String ID (VD: "NODE_004")
 * @param gatewayId Gateway ID (VD: "GW_001")
 */
void nvs_saveNodeConfig(uint8_t nodeId, const char* nodeIdStr, const char* gatewayId);

/**
 * Xóa cấu hình (factory reset)
 */
void nvs_clearConfig();
