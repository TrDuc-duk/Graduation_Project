#include "wifi_store.h"
#include <Arduino.h>
#include <Preferences.h>
#include <string.h>
#include "common/debug.h"

// =============================================================================
//  WIFI STORE IMPLEMENTATION
//  Lưu tối đa 5 WiFi credentials trong NVS namespace "wifi_creds"
//  Keys: "count" (uint8), "ssid_0".."ssid_4", "pass_0".."pass_4"
// =============================================================================

static WifiCredential credentials[WIFI_STORE_MAX];
static uint8_t credCount = 0;
static Preferences wifiPrefs;
static const char* WIFI_NS = "wifi_creds";

static void wifi_store_save() {
    wifiPrefs.begin(WIFI_NS, false);
    wifiPrefs.putUChar("count", credCount);

    for (uint8_t i = 0; i < credCount; i++) {
        char keyS[8], keyP[8];
        snprintf(keyS, sizeof(keyS), "ssid_%d", i);
        snprintf(keyP, sizeof(keyP), "pass_%d", i);
        wifiPrefs.putString(keyS, credentials[i].ssid);
        wifiPrefs.putString(keyP, credentials[i].password);
    }

    // Xóa các slot không dùng
    for (uint8_t i = credCount; i < WIFI_STORE_MAX; i++) {
        char keyS[8], keyP[8];
        snprintf(keyS, sizeof(keyS), "ssid_%d", i);
        snprintf(keyP, sizeof(keyP), "pass_%d", i);
        wifiPrefs.remove(keyS);
        wifiPrefs.remove(keyP);
    }

    wifiPrefs.end();
}

void wifi_store_load() {
    wifiPrefs.begin(WIFI_NS, true);  // read-only
    credCount = wifiPrefs.getUChar("count", 0);
    if (credCount > WIFI_STORE_MAX) credCount = WIFI_STORE_MAX;

    for (uint8_t i = 0; i < credCount; i++) {
        char keyS[8], keyP[8];
        snprintf(keyS, sizeof(keyS), "ssid_%d", i);
        snprintf(keyP, sizeof(keyP), "pass_%d", i);

        String s = wifiPrefs.getString(keyS, "");
        String p = wifiPrefs.getString(keyP, "");
        strncpy(credentials[i].ssid, s.c_str(), sizeof(credentials[i].ssid) - 1);
        credentials[i].ssid[sizeof(credentials[i].ssid) - 1] = '\0';
        strncpy(credentials[i].password, p.c_str(), sizeof(credentials[i].password) - 1);
        credentials[i].password[sizeof(credentials[i].password) - 1] = '\0';
    }

    wifiPrefs.end();

    LOG_INFO("WiFiStore", "Đã tải %d WiFi credential(s) từ NVS", credCount);
    for (uint8_t i = 0; i < credCount; i++) {
        LOG_INFO("WiFiStore", "  [%d] %s", i, credentials[i].ssid);
    }
}

uint8_t wifi_store_count() {
    return credCount;
}

const WifiCredential* wifi_store_getAll() {
    return credentials;
}

bool wifi_store_add(const char* ssid, const char* password) {
    if (!ssid || strlen(ssid) == 0) return false;

    // Kiểm tra SSID đã tồn tại → cập nhật password
    for (uint8_t i = 0; i < credCount; i++) {
        if (strcmp(credentials[i].ssid, ssid) == 0) {
            strncpy(credentials[i].password, password ? password : "", sizeof(credentials[i].password) - 1);
            credentials[i].password[sizeof(credentials[i].password) - 1] = '\0';
            wifi_store_save();
            LOG_INFO("WiFiStore", "Cập nhật password cho '%s'", ssid);
            return true;
        }
    }

    // Nếu đầy → xóa cái cũ nhất (slot 0), dịch lên
    if (credCount >= WIFI_STORE_MAX) {
        LOG_INFO("WiFiStore", "Store đầy, xóa '%s' để thêm '%s'", credentials[0].ssid, ssid);
        for (uint8_t i = 0; i < WIFI_STORE_MAX - 1; i++) {
            credentials[i] = credentials[i + 1];
        }
        credCount = WIFI_STORE_MAX - 1;
    }

    // Thêm vào cuối
    strncpy(credentials[credCount].ssid, ssid, sizeof(credentials[credCount].ssid) - 1);
    credentials[credCount].ssid[sizeof(credentials[credCount].ssid) - 1] = '\0';
    strncpy(credentials[credCount].password, password ? password : "", sizeof(credentials[credCount].password) - 1);
    credentials[credCount].password[sizeof(credentials[credCount].password) - 1] = '\0';
    credCount++;

    wifi_store_save();
    LOG_INFO("WiFiStore", "Đã thêm WiFi '%s' (total: %d)", ssid, credCount);
    return true;
}

void wifi_store_clear() {
    credCount = 0;
    memset(credentials, 0, sizeof(credentials));

    wifiPrefs.begin(WIFI_NS, false);
    wifiPrefs.clear();
    wifiPrefs.end();

    LOG_MSG("WiFiStore", "Đã xóa toàn bộ WiFi credentials");
}
