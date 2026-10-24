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

// =============================================================================
//  CAPTIVE PORTAL IMPLEMENTATION — Sensor Node
//  Khác Gateway:
//    - Có bước fetch danh sách gateway từ server
//    - Sau provisioning: TẮT WiFi hoàn toàn, chỉ dùng LoRa
// =============================================================================

static WebServer webServer(80);
static DNSServer dnsServer;

static const char* AP_SSID = "AirQuality-Node-Setup";
static const byte DNS_PORT = 53;

// Cache WiFi credentials sau khi kết nối thành công (dùng lại cho /save)
static String cachedSsid = "";
static String cachedPass = "";

// LED nhấp nháy
static unsigned long lastLedToggle = 0;
static bool ledState = false;

static void blinkLed() {
    if (millis() - lastLedToggle > 250) {
        lastLedToggle = millis();
        ledState = !ledState;
        digitalWrite(LED_PROVISION_PIN, ledState ? HIGH : LOW);
    }
}

// ───── Helper: Kết nối WiFi STA trong khi vẫn giữ AP ─────
static bool connectWifiSTA(const char* ssid, const char* pass, uint32_t timeoutMs = 15000) {
    WiFi.mode(WIFI_AP_STA);
    WiFi.begin(ssid, pass);

    unsigned long start = millis();
    while (WiFi.status() != WL_CONNECTED) {
        if (millis() - start > timeoutMs) return false;
        delay(500);
        blinkLed();
    }
    return true;
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

// ───── Handler: Kết nối WiFi + Fetch danh sách Gateway ─────
static void handleGateways() {
    if (!webServer.hasArg("plain")) {
        webServer.send(400, "application/json", "{\"success\":false,\"error\":\"No body\"}");
        return;
    }

    String body = webServer.arg("plain");
    JsonDocument doc;
    deserializeJson(doc, body);

    const char* wifiSsid  = doc["wifi_ssid"];
    const char* wifiPass  = doc["wifi_pass"];

    if (!wifiSsid) {
        webServer.send(400, "application/json", "{\"success\":false,\"error\":\"Thiếu WiFi SSID\"}");
        return;
    }

    // Kết nối WiFi STA (giữ AP cho client)
    LOG_INFO("Portal", "Kết nối WiFi: %s", wifiSsid);
    if (!connectWifiSTA(wifiSsid, wifiPass ? wifiPass : "")) {
        webServer.send(200, "application/json",
            "{\"success\":false,\"error\":\"Không kết nối được WiFi. Kiểm tra mật khẩu.\"}");
        return;
    }

    LOG_INFO("Portal", "✅ WiFi OK! IP: %s", WiFi.localIP().toString().c_str());

    // Cache credentials
    cachedSsid = wifiSsid;
    cachedPass = wifiPass ? wifiPass : "";

    // Fetch danh sách gateway từ server (dùng SERVER_BASE_URL cấu hình cứng)
    String apiUrl = String(SERVER_BASE_URL) + "/api/v1/provision/gateways?provision_key=" + String(PROVISION_KEY);
    LOG_INFO("Portal", "Fetch gateways: %s", apiUrl.c_str());

    HTTPClient http;
    WiFiClientSecure secureClient;
    secureClient.setInsecure(); // Skip cert verify (provisioning chỉ chạy 1 lần)
    http.begin(secureClient, apiUrl);
    http.setTimeout(10000);

    int httpCode = http.GET();
    String response = http.getString();
    http.end();

    LOG_INFO("Portal", "Server: %d — %s", httpCode, response.c_str());

    if (httpCode != 200) {
        webServer.send(200, "application/json",
            "{\"success\":false,\"error\":\"Không thể kết nối server.\"}");
        return;
    }

    // Parse response → forward danh sách gateway cho client
    JsonDocument resDoc;
    deserializeJson(resDoc, response);

    JsonDocument outDoc;
    outDoc["success"] = true;
    outDoc["gateways"] = resDoc["data"];

    String outJson;
    serializeJson(outDoc, outJson);
    webServer.send(200, "application/json", outJson);
}

// ───── Handler: Đăng ký Node + Lưu NVS ─────
static void handleSave() {
    if (!webServer.hasArg("plain")) {
        webServer.send(400, "application/json", "{\"success\":false,\"error\":\"No body\"}");
        return;
    }

    String body = webServer.arg("plain");
    JsonDocument doc;
    deserializeJson(doc, body);

    const char* nodeName   = doc["name"];
    const char* gatewayId  = doc["gateway_id"];

    if (!nodeName || !gatewayId) {
        webServer.send(400, "application/json", "{\"success\":false,\"error\":\"Thiếu thông tin\"}");
        return;
    }

    // Đảm bảo WiFi STA vẫn kết nối
    if (WiFi.status() != WL_CONNECTED) {
        LOG_MSG("Portal", "WiFi mất, kết nối lại...");
        if (!connectWifiSTA(cachedSsid.c_str(), cachedPass.c_str())) {
            webServer.send(200, "application/json",
                "{\"success\":false,\"error\":\"Mất kết nối WiFi\"}");
            return;
        }
    }

    // ── Gọi API đăng ký node (dùng SERVER_BASE_URL cấu hình cứng) ──
    String apiUrl = String(SERVER_BASE_URL) + "/api/v1/provision/node";
    LOG_INFO("Portal", "Đăng ký node: %s", apiUrl.c_str());

    HTTPClient http;
    WiFiClientSecure secureClient;
    secureClient.setInsecure();
    http.begin(secureClient, apiUrl);
    http.addHeader("Content-Type", "application/json");
    http.setTimeout(10000);

    JsonDocument reqDoc;
    reqDoc["provision_key"] = PROVISION_KEY;
    reqDoc["name"]          = nodeName;
    reqDoc["gateway_id"]    = gatewayId;

    // Tọa độ tuỳ chọn
    if (doc.containsKey("lat") && doc.containsKey("lng")) {
        reqDoc["lat"] = doc["lat"];
        reqDoc["lng"] = doc["lng"];
    }

    String reqBody;
    serializeJson(reqDoc, reqBody);

    int httpCode = http.POST(reqBody);
    String response = http.getString();
    http.end();

    LOG_INFO("Portal", "Server: %d — %s", httpCode, response.c_str());

    if (httpCode != 201) {
        JsonDocument errDoc;
        deserializeJson(errDoc, response);
        String errMsg = errDoc["error"] | "Server trả lỗi";
        String errJson = "{\"success\":false,\"error\":\"" + errMsg + "\"}";
        webServer.send(200, "application/json", errJson);
        return;
    }

    // ── Parse node_id và node_numeric_id ──
    JsonDocument resDoc;
    deserializeJson(resDoc, response);

    const char* nodeIdStr = resDoc["data"]["id"];
    uint8_t nodeNumericId = resDoc["data"]["node_numeric_id"] | 0;

    if (!nodeIdStr || nodeNumericId == 0) {
        webServer.send(200, "application/json",
            "{\"success\":false,\"error\":\"Server không trả về Node ID hợp lệ\"}");
        return;
    }

    LOG_INFO("Portal", "✅ Node registered! ID: %s (0x%02X), GW: %s",
             nodeIdStr, nodeNumericId, gatewayId);

    // ── Lưu vào NVS ──
    nvs_saveNodeConfig(nodeNumericId, nodeIdStr, gatewayId);

    // ── Response thành công ──
    String successJson = "{\"success\":true,\"node_id\":\"" + String(nodeIdStr) + "\"}";
    webServer.send(200, "application/json", successJson);

    // ── Delay → Reboot ──
    LOG_MSG("Portal", "TẮT WiFi → Khởi động lại vào chế độ LoRa...");
    delay(3000);
    WiFi.disconnect(true);
    WiFi.mode(WIFI_OFF);
    delay(500);
    ESP.restart();
}

// ───── Handler: Redirect ─────
static void handleNotFound() {
    webServer.sendHeader("Location", "http://192.168.4.1", true);
    webServer.send(302, "text/plain", "");
}

void startCaptivePortal() {
    LOG_MSG("Portal", "═══════════════════════════════════════");
    LOG_MSG("Portal", "  CHẾ ĐỘ CẤU HÌNH (Sensor Node)");
    LOG_MSG("Portal", "═══════════════════════════════════════");

    // LED provisioning
    pinMode(LED_PROVISION_PIN, OUTPUT);

    // ── Bật WiFi AP ──
    WiFi.mode(WIFI_AP);
    WiFi.softAP(AP_SSID);
    delay(100);

    IPAddress apIP = WiFi.softAPIP();
    LOG_INFO("Portal", "WiFi AP: \"%s\"", AP_SSID);
    LOG_INFO("Portal", "IP: %s", apIP.toString().c_str());

    // ── DNS redirect ──
    dnsServer.start(DNS_PORT, "*", apIP);

    // ── Web Server routes ──
    webServer.on("/",         HTTP_GET,  handleRoot);
    webServer.on("/scan",     HTTP_GET,  handleScan);
    webServer.on("/gateways", HTTP_POST, handleGateways);
    webServer.on("/save",     HTTP_POST, handleSave);
    webServer.onNotFound(handleNotFound);
    webServer.begin();

    LOG_MSG("Portal", "Web server đang chạy!");
    LOG_MSG("Portal", "Kết nối WiFi \"AirQuality-Node-Setup\" trên điện thoại.");
    LOG_MSG("Portal", "");

    // ── Blocking loop ──
    while (true) {
        dnsServer.processNextRequest();
        webServer.handleClient();
        blinkLed();
        delay(10);
    }
}
