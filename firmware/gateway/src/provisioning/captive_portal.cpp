#include "captive_portal.h"
#include <Arduino.h>
#include <WiFi.h>
#include <WebServer.h>
#include <DNSServer.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>

#include "portal_html.h"
#include "config.h"
#include "common/debug.h"
#include "core/nvs_config.h"
#include "core/wifi_store.h"
#include "drivers/oled_display.h"

// =============================================================================
//  CAPTIVE PORTAL IMPLEMENTATION — Gateway
//  WiFi AP mode + DNS redirect + Web Server
//
//  Flow:
//  1. ESP32 phát WiFi AP "AirQuality-GW-Setup"
//  2. User kết nối điện thoại → trang web tự mở
//  3. User chọn WiFi, nhập server URL, đặt tên
//  4. ESP32 kết nối WiFi → gọi API đăng ký → lưu NVS → reboot
// =============================================================================

static WebServer webServer(80);
static DNSServer dnsServer;

static const char* AP_SSID = "AirQuality-GW-Setup";
static const byte DNS_PORT = 53;

// LED nhấp nháy cho chế độ provisioning
static unsigned long lastLedToggle = 0;
static bool ledState = false;

static void blinkProvisioningLed() {
    if (millis() - lastLedToggle > 250) {  // 2Hz blink
        lastLedToggle = millis();
        ledState = !ledState;
        digitalWrite(LED_STATUS_PIN, ledState ? HIGH : LOW);
    }
}

// ───── Handler: Trang chủ ─────
static void handleRoot() {
    webServer.send(200, "text/html", PORTAL_HTML);
}

// ───── Handler: Quét WiFi ─────
static void handleScan() {
    LOG_MSG("Portal", "Đang quét WiFi...");
    int n = WiFi.scanNetworks();

    JsonDocument doc;
    JsonArray networks = doc["networks"].to<JsonArray>();

    for (int i = 0; i < n; i++) {
        JsonObject net = networks.add<JsonObject>();
        net["ssid"]   = WiFi.SSID(i);
        net["rssi"]   = WiFi.RSSI(i);
        net["secure"] = WiFi.encryptionType(i) != WIFI_AUTH_OPEN;
    }

    WiFi.scanDelete();

    String json;
    serializeJson(doc, json);
    webServer.send(200, "application/json", json);
    LOG_INFO("Portal", "Tìm thấy %d mạng WiFi", n);
}

// ───── Handler: Lưu cấu hình + Đăng ký server ─────
static void handleSave() {
    if (!webServer.hasArg("plain")) {
        webServer.send(400, "application/json", "{\"success\":false,\"error\":\"No body\"}");
        return;
    }

    String body = webServer.arg("plain");
    JsonDocument doc;
    DeserializationError err = deserializeJson(doc, body);
    if (err) {
        webServer.send(400, "application/json", "{\"success\":false,\"error\":\"Invalid JSON\"}");
        return;
    }

    const char* wifiSsid   = doc["wifi_ssid"];
    const char* wifiPass   = doc["wifi_pass"];
    const char* gwName     = doc["name"];
    const char* gwLocation = doc["location_desc"];

    if (!wifiSsid || !gwName) {
        webServer.send(400, "application/json", "{\"success\":false,\"error\":\"Thiếu thông tin\"}");
        return;
    }

    LOG_INFO("Portal", "WiFi: %s, Server: %s, Name: %s", wifiSsid, SERVER_BASE_URL, gwName);

    // ── Bước 1: Kết nối WiFi STA (giữ AP) ──
    LOG_MSG("Portal", "Đang kết nối WiFi...");
    WiFi.mode(WIFI_AP_STA);
    WiFi.begin(wifiSsid, wifiPass);

    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - start > 15000) {
            LOG_MSG("Portal", "❌ WiFi timeout!");
            WiFi.disconnect();
            webServer.send(200, "application/json",
                "{\"success\":false,\"error\":\"Không kết nối được WiFi. Kiểm tra mật khẩu.\"}");
            return;
        }
        delay(500);
        blinkProvisioningLed();
    }
    LOG_INFO("Portal", "✅ WiFi connected! IP: %s", WiFi.localIP().toString().c_str());

    // ── Bước 2: Gọi API đăng ký gateway (dùng SERVER_BASE_URL cấu hình cứng) ──
    String apiUrl = String(SERVER_BASE_URL) + "/api/v1/provision/gateway";
    LOG_INFO("Portal", "Đăng ký gateway: %s", apiUrl.c_str());

    HTTPClient http;
    WiFiClientSecure secureClient;
    secureClient.setInsecure();
    http.begin(secureClient, apiUrl);
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(10000);

    JsonDocument reqDoc;
    reqDoc["provision_key"] = PROVISION_KEY;
    reqDoc["name"]          = gwName;
    if (gwLocation && strlen(gwLocation) > 0) {
        reqDoc["location_desc"] = gwLocation;
    }

    String reqBody;
    serializeJson(reqDoc, reqBody);

    int httpCode = http.POST(reqBody);
    String response = http.getString();
    http.end();

    LOG_INFO("Portal", "Server response: %d — %s", httpCode, response.c_str());

    if (httpCode != 201) {
        JsonDocument errDoc;
        deserializeJson(errDoc, response);
        String errMsg = errDoc["error"] | "Server trả lỗi";
        String errJson = "{\"success\":false,\"error\":\"" + errMsg + "\"}";
        webServer.send(200, "application/json", errJson);
        WiFi.disconnect();
        return;
    }

    // ── Bước 3: Parse gateway_id từ response ──
    JsonDocument resDoc;
    deserializeJson(resDoc, response);
    const char* gatewayId = resDoc["data"]["id"];

    if (!gatewayId) {
        webServer.send(200, "application/json",
            "{\"success\":false,\"error\":\"Server không trả về Gateway ID\"}");
        WiFi.disconnect();
        return;
    }

    LOG_INFO("Portal", "✅ Đã đăng ký! Gateway ID: %s", gatewayId);

    // ── Bước 4: Lưu cấu hình vào NVS ──
    wifi_store_add(wifiSsid, wifiPass ? wifiPass : "");
    nvs_saveGatewayConfig(gatewayId, "", "",
                          SERVER_BASE_URL, PROVISION_KEY);

    // ── Bước 5: Trả response thành công ──
    String successJson = "{\"success\":true,\"gateway_id\":\"" + String(gatewayId) + "\"}";
    webServer.send(200, "application/json", successJson);

    // ── Bước 6: Delay cho client nhận response → Reboot ──
    LOG_MSG("Portal", "Khởi động lại trong 3 giây...");
    delay(3000);
    ESP.restart();
}

// ───── Handler: Redirect mọi request chưa match → trang chủ ─────
static void handleNotFound() {
    webServer.sendHeader("Location", "http://192.168.4.1", true);
    webServer.send(302, "text/plain", "");
}

void startCaptivePortal() {
    LOG_MSG("Portal", "═══════════════════════════════════════");
    LOG_MSG("Portal", "  CHẾ ĐỘ CẤU HÌNH (Captive Portal)");
    LOG_MSG("Portal", "═══════════════════════════════════════");

    // LED provisioning
    pinMode(LED_STATUS_PIN, OUTPUT);
    pinMode(LED_WIFI_PIN, OUTPUT);
    digitalWrite(LED_WIFI_PIN, LOW);

    // ── Bật WiFi AP ──
    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_SSID);
    delay(100);

    IPAddress apIP = WiFi.softAPIP();
    LOG_INFO("Portal", "WiFi AP: \"%s\"", AP_SSID);
    LOG_INFO("Portal", "IP: %s", apIP.toString().c_str());

    // ── DNS redirect: mọi domain → IP của ESP32 ──
    dnsServer.start(DNS_PORT, "*", apIP);

    // ── Web Server routes ──
    webServer.on("/",     HTTP_GET,  handleRoot);
    webServer.on("/scan", HTTP_GET,  handleScan);
    webServer.on("/save", HTTP_POST, handleSave);
    webServer.onNotFound(handleNotFound);
    webServer.begin();

    LOG_MSG("Portal", "Web server đang chạy!");
    LOG_MSG("Portal", "Kết nối WiFi \"AirQuality-GW-Setup\" trên điện thoại để cấu hình.");
    LOG_MSG("Portal", "");

    // Hiển thị thông tin provisioning trên OLED
    oled_showProvisioning();

    // ── Main loop (blocking — chờ user cấu hình) ──
    while (true) {
        dnsServer.processNextRequest();
        webServer.handleClient();
        blinkProvisioningLed();
        delay(10);
    }
}
