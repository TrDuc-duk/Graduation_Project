#include "nvs_config.h"
#include <Arduino.h>
#include <Preferences.h>
#include "common/debug.h"

// =============================================================================
//  NVS CONFIG IMPLEMENTATION — Sensor Node
//  Lưu node_id + gateway_id vào ESP32 Preferences
//  Namespace: "node_config"
// =============================================================================

// ===== Runtime Config Variables =====
uint8_t cfg_nodeId         = 0;
char    cfg_nodeIdStr[16]  = "";
char    cfg_gatewayId[16]  = "";

static Preferences prefs;
static const char* NVS_NAMESPACE = "node_config";

void nvs_loadConfig() {
    prefs.begin(NVS_NAMESPACE, true);  // read-only

    cfg_nodeId = prefs.getUChar("node_id", 0);
    String nidStr = prefs.getString("node_id_str", "");
    String gwId   = prefs.getString("gateway_id", "");

    prefs.end();

    strncpy(cfg_nodeIdStr, nidStr.c_str(), sizeof(cfg_nodeIdStr) - 1);
    strncpy(cfg_gatewayId, gwId.c_str(),   sizeof(cfg_gatewayId) - 1);

    LOG_MSG("NVS", "Config loaded:");
    LOG_INFO("NVS", "  Node ID    : 0x%02X (%s)", cfg_nodeId,
             strlen(cfg_nodeIdStr) > 0 ? cfg_nodeIdStr : "chưa cấu hình");
    LOG_INFO("NVS", "  Gateway    : %s",
             strlen(cfg_gatewayId) > 0 ? cfg_gatewayId : "chưa cấu hình");
}

bool nvs_isProvisioned() {
    return cfg_nodeId > 0 && strlen(cfg_gatewayId) > 0;
}

void nvs_saveNodeConfig(uint8_t nodeId, const char* nodeIdStr, const char* gatewayId) {
    prefs.begin(NVS_NAMESPACE, false);  // read-write

    prefs.putUChar("node_id", nodeId);
    prefs.putString("node_id_str", nodeIdStr);
    prefs.putString("gateway_id", gatewayId);

    prefs.end();

    LOG_INFO("NVS", "Config saved! NodeID=0x%02X (%s), GW=%s",
             nodeId, nodeIdStr, gatewayId);
}

void nvs_clearConfig() {
    prefs.begin(NVS_NAMESPACE, false);
    prefs.clear();
    prefs.end();

    LOG_MSG("NVS", "⚠ Config đã xóa! Khởi động lại vào chế độ provisioning...");
}
