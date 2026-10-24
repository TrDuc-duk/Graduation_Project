#include "wifi_manager.h"
#include <Arduino.h>
#include <WiFi.h>
#include "config.h"
#include "common/debug.h"
#include "core/wifi_store.h"

// =============================================================================
//  WIFI MANAGER IMPLEMENTATION
//  Scan WiFi xung quanh → match với wifi_store → kết nối RSSI mạnh nhất
//  Auto-reconnect: thử SSID hiện tại, nếu fail nhiều lần → re-scan
// =============================================================================

static unsigned long lastReconnectAttempt = 0;
static uint8_t reconnectFailCount = 0;
static char ipBuffer[16] = "0.0.0.0";
static char ssidBuffer[64] = "";

// Số lần reconnect thất bại trước khi chạy lại autoConnect
#define RECONNECT_RESCAN_THRESHOLD 3

static void cacheConnectionInfo() {
    IPAddress ip = WiFi.localIP();
    snprintf(ipBuffer, sizeof(ipBuffer), "%d.%d.%d.%d", ip[0], ip[1], ip[2], ip[3]);
    strncpy(ssidBuffer, WiFi.SSID().c_str(), sizeof(ssidBuffer) - 1);
    ssidBuffer[sizeof(ssidBuffer) - 1] = '\0';
}

static bool tryConnect(const char* ssid, const char* password, unsigned long timeoutMs) {
    LOG_INFO("WiFi", "Thử kết nối '%s'...", ssid);

    WiFi.disconnect();
    delay(100);
    WiFi.begin(ssid, password);

    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - start > timeoutMs) {
            LOG_INFO("WiFi", "  ❌ Timeout '%s'", ssid);
            WiFi.disconnect();
            return false;
        }
        delay(500);
    }

    cacheConnectionInfo();
    LOG_INFO("WiFi", "  ✅ Kết nối '%s' OK! IP: %s, RSSI: %d dBm", ssid, ipBuffer, WiFi.RSSI());
    return true;
}

bool wifi_autoConnect() {
    WiFi.mode(WIFI_STA);

    uint8_t storeCount = wifi_store_count();
    if (storeCount == 0) {
        LOG_MSG("WiFi", "Không có WiFi nào trong store.");
        return false;
    }

    // Bước 1: Quét WiFi xung quanh
    LOG_MSG("WiFi", "Đang quét WiFi...");
    int found = WiFi.scanNetworks();
    if (found <= 0) {
        LOG_MSG("WiFi", "Không tìm thấy mạng WiFi nào.");
        WiFi.scanDelete();
        return false;
    }
    LOG_INFO("WiFi", "Tìm thấy %d mạng WiFi", found);

    // Bước 2: Tìm các SSID có trong store, sắp xếp theo RSSI giảm dần
    const WifiCredential* creds = wifi_store_getAll();

    // Mảng index + RSSI cho các mạng match
    struct Match {
        uint8_t credIdx;  // index trong wifi_store
        int32_t rssi;
    };
    Match matches[WIFI_STORE_MAX];
    uint8_t matchCount = 0;

    for (uint8_t ci = 0; ci < storeCount && matchCount < WIFI_STORE_MAX; ci++) {
        int32_t bestRssi = -999;
        bool matched = false;

        for (int si = 0; si < found; si++) {
            if (WiFi.SSID(si) == creds[ci].ssid) {
                if (WiFi.RSSI(si) > bestRssi) {
                    bestRssi = WiFi.RSSI(si);
                    matched = true;
                }
            }
        }

        if (matched) {
            matches[matchCount].credIdx = ci;
            matches[matchCount].rssi = bestRssi;
            matchCount++;
            LOG_INFO("WiFi", "  Match: '%s' (RSSI: %d dBm)", creds[ci].ssid, bestRssi);
        }
    }

    WiFi.scanDelete();

    if (matchCount == 0) {
        LOG_MSG("WiFi", "Không có WiFi nào trong store khớp với mạng xung quanh.");
        return false;
    }

    // Sắp xếp theo RSSI giảm dần (bubble sort, tối đa 5 phần tử)
    for (uint8_t i = 0; i < matchCount - 1; i++) {
        for (uint8_t j = i + 1; j < matchCount; j++) {
            if (matches[j].rssi > matches[i].rssi) {
                Match tmp = matches[i];
                matches[i] = matches[j];
                matches[j] = tmp;
            }
        }
    }

    // Bước 3: Thử kết nối từng cái, RSSI mạnh nhất trước
    for (uint8_t i = 0; i < matchCount; i++) {
        const WifiCredential* c = &creds[matches[i].credIdx];
        if (tryConnect(c->ssid, c->password, WIFI_CONNECT_TIMEOUT_MS)) {
            reconnectFailCount = 0;
            return true;
        }
    }

    LOG_MSG("WiFi", "Không kết nối được WiFi nào trong danh sách.");
    return false;
}

bool wifi_isConnected() {
    return WiFi.status() == WL_CONNECTED;
}

void wifi_reconnectIfNeeded() {
    if (wifi_isConnected()) {
        // ESP32 có thể auto-reconnect ngầm (WiFi driver tự kết nối lại)
        // → cần cập nhật cache IP/SSID nếu chưa có
        if (ipBuffer[0] == '0' && ipBuffer[1] == '.') {
            cacheConnectionInfo();
            LOG_INFO("WiFi", "✅ Đã kết nối (auto-reconnect)! IP: %s, RSSI: %d dBm", ipBuffer, WiFi.RSSI());
        }
        reconnectFailCount = 0;
        return;
    }

    unsigned long now = millis();
    if (now - lastReconnectAttempt < WIFI_RETRY_DELAY_MS) return;
    lastReconnectAttempt = now;

    reconnectFailCount++;
    LOG_INFO("WiFi", "⚠ Mất kết nối! Thử lại... (lần %d)", reconnectFailCount);

    if (reconnectFailCount >= RECONNECT_RESCAN_THRESHOLD) {
        // Đã thất bại nhiều lần → quét lại toàn bộ
        LOG_MSG("WiFi", "Reconnect thất bại nhiều lần → Re-scan WiFi...");
        if (wifi_autoConnect()) {
            reconnectFailCount = 0;
        }
        return;
    }

    // Thử kết nối lại WiFi hiện tại (nhanh hơn full scan)
    WiFi.disconnect();
    WiFi.reconnect();
    delay(100);

    if (wifi_isConnected()) {
        cacheConnectionInfo();
        LOG_INFO("WiFi", "✅ Kết nối lại thành công! IP: %s", ipBuffer);
        reconnectFailCount = 0;
    }
}

int32_t wifi_getRSSI() {
    return WiFi.RSSI();
}

const char* wifi_getIP() {
    return ipBuffer;
}

const char* wifi_getSSID() {
    return ssidBuffer;
}
