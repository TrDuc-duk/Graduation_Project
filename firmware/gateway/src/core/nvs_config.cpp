#include "nvs_config.h"
#include <Arduino.h>
#include <Preferences.h>
#include "config.h"
#include "common/debug.h"
#include "core/wifi_store.h"

// =============================================================================
//  NVS CONFIG IMPLEMENTATION
//  Dùng ESP32 Preferences library (wrapper NVS) để lưu cấu hình persistent
//  Namespace: "gw_config"
// =============================================================================

// ===== Runtime Config Variables =====
char cfg_gatewayId[16]     = "";
char cfg_wifiSsid[64]      = "";
char cfg_wifiPassword[64]  = "";
char cfg_apiUrl[128]       = "";
char cfg_serverBase[128]   = "";
char cfg_provisionKey[64]  = "";

static Preferences prefs;
static const char* NVS_NAMESPACE = "gw_config";

void nvs_loadConfig() {
    prefs.begin(NVS_NAMESPACE, true);  // read-only

    String gid  = prefs.getString("gateway_id", "");
    String ssid = prefs.getString("wifi_ssid", "");
    String pass = prefs.getString("wifi_pass", "");
    String base = prefs.getString("server_base", SERVER_BASE_URL);
    String pkey = prefs.getString("prov_key", PROVISION_KEY);

    prefs.end();

    // Copy vào biến runtime (char arrays)
    strncpy(cfg_gatewayId,    gid.c_str(),  sizeof(cfg_gatewayId) - 1);
    strncpy(cfg_wifiSsid,     ssid.c_str(), sizeof(cfg_wifiSsid) - 1);
    strncpy(cfg_wifiPassword, pass.c_str(), sizeof(cfg_wifiPassword) - 1);
    strncpy(cfg_serverBase,   base.c_str(), sizeof(cfg_serverBase) - 1);
    strncpy(cfg_provisionKey, pkey.c_str(), sizeof(cfg_provisionKey) - 1);

    // Tạo API URL từ server base: base + "/api/v1/telemetry"
    if (strlen(cfg_serverBase) > 0) {
        snprintf(cfg_apiUrl, sizeof(cfg_apiUrl), "%s/api/v1/telemetry", cfg_serverBase);
    }

    LOG_MSG("NVS", "Config loaded:");
    LOG_INFO("NVS", "  Gateway ID : %s", strlen(cfg_gatewayId) > 0 ? cfg_gatewayId : "(chưa cấu hình)");
    LOG_INFO("NVS", "  WiFi SSID  : %s", strlen(cfg_wifiSsid) > 0 ? cfg_wifiSsid : "(chưa cấu hình)");
    LOG_INFO("NVS", "  Server     : %s", strlen(cfg_serverBase) > 0 ? cfg_serverBase : "(chưa cấu hình)");
}

bool nvs_isProvisioned() {
    return strlen(cfg_gatewayId) > 0 && strlen(cfg_serverBase) > 0;
}

void nvs_saveGatewayConfig(const char* gatewayId,
                           const char* wifiSsid,
                           const char* wifiPassword,
                           const char* serverBaseUrl,
                           const char* provisionKey) {
    prefs.begin(NVS_NAMESPACE, false);  // read-write

    prefs.putString("gateway_id",  gatewayId);
    prefs.putString("wifi_ssid",   wifiSsid);
    prefs.putString("wifi_pass",   wifiPassword);
    prefs.putString("server_base", serverBaseUrl);
    prefs.putString("prov_key",    provisionKey);

    prefs.end();

    LOG_INFO("NVS", "Config saved! GW=%s, SSID=%s, Server=%s",
             gatewayId, wifiSsid, serverBaseUrl);
}

void nvs_clearConfig() {
    prefs.begin(NVS_NAMESPACE, false);
    prefs.clear();
    prefs.end();

    wifi_store_clear();

    LOG_MSG("NVS", "⚠ Config đã xóa! Khởi động lại vào chế độ provisioning...");
}
