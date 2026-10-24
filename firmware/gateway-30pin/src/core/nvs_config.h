#pragma once
#include <stdbool.h>
#include <stdint.h>

// =============================================================================
//  NVS CONFIG — Lưu/đọc cấu hình từ Non-Volatile Storage (ESP32 Preferences)
//  Thay thế #define constants bằng runtime variables
// =============================================================================

// ===== Runtime Config Variables (đọc từ NVS khi boot) =====
extern char     cfg_gatewayId[16];     // VD: "GW_001"
extern char     cfg_wifiSsid[64];      // SSID WiFi
extern char     cfg_wifiPassword[64];  // Password WiFi
extern char     cfg_apiUrl[128];       // VD: "http://192.168.1.100:3000/api/v1/telemetry"
extern char     cfg_serverBase[128];   // VD: "http://192.168.1.100:3000" (cho provisioning)
extern char     cfg_provisionKey[64];  // Provisioning secret key

/**
 * Đọc cấu hình từ NVS vào biến runtime
 * Gọi 1 lần trong setup()
 */
void nvs_loadConfig();

/**
 * Kiểm tra thiết bị đã được cấu hình chưa
 * @return true nếu có GATEWAY_ID + WIFI_SSID trong NVS
 */
bool nvs_isProvisioned();

/**
 * Lưu cấu hình gateway vào NVS
 * Gọi sau khi provisioning thành công
 */
void nvs_saveGatewayConfig(const char* gatewayId,
                           const char* wifiSsid,
                           const char* wifiPassword,
                           const char* serverBaseUrl,
                           const char* provisionKey);

/**
 * Xóa toàn bộ cấu hình (factory reset)
 * Gọi khi giữ nút BOOT 5 giây
 */
void nvs_clearConfig();
