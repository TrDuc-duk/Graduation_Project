#include <Arduino.h>
#include "config.h"
#include "common/debug.h"
#include "common/packet.h"

// Core
#include "core/nvs_config.h"
#include "core/packet_buffer.h"
#include "core/wifi_store.h"

// Provisioning
#include "provisioning/captive_portal.h"

// Drivers
#include "drivers/wifi_manager.h"
#include "drivers/lora_receiver.h"
#include "drivers/oled_display.h"

// Network
#include "net/http_client.h"

// =============================================================================
//  MAIN.CPP - Air Quality Gateway (Superloop)
//
//  Kiến trúc:
//    setup() → NVS → WiFi Store → Migration → Auto-connect hoặc Captive Portal
//    loop()  → WiFi reconnect + LoRa poll + Buffer flush + Factory Reset
//
//  Chế độ:
//    - Auto-Connect: Quét WiFi xung quanh, kết nối WiFi đã lưu
//    - Captive Portal: Khi chưa provisioned hoặc không tìm được WiFi
//    - Factory Reset: Giữ nút BOOT 5 giây → xóa NVS → reboot
// =============================================================================

static unsigned long lastFlushTime = 0;
static unsigned long lastHeartbeatTime = 0;
static unsigned long resetBtnPressStart = 0;
static bool resetBtnPressed = false;

// ===== LED Helper =====
void led_init() {
    pinMode(LED_WIFI_PIN, OUTPUT);
    pinMode(LED_STATUS_PIN, OUTPUT);
    digitalWrite(LED_WIFI_PIN, LOW);
    digitalWrite(LED_STATUS_PIN, LOW);
}

void led_update() {
    // LED WiFi: sáng = connected, tắt = disconnected
    digitalWrite(LED_WIFI_PIN, wifi_isConnected() ? HIGH : LOW);
}

// ===== Factory Reset Check =====
void checkFactoryReset() {
    bool btnState = (digitalRead(RESET_BUTTON_PIN) == LOW);  // BOOT button active LOW

    if (btnState && !resetBtnPressed) {
        // Bắt đầu nhấn
        resetBtnPressed = true;
        resetBtnPressStart = millis();
    } else if (!btnState && resetBtnPressed) {
        // Thả nút
        resetBtnPressed = false;
    } else if (btnState && resetBtnPressed) {
        // Đang giữ nút
        if (millis() - resetBtnPressStart >= RESET_HOLD_TIME_MS) {
            LOG_MSG("RESET", "");
            LOG_MSG("RESET", "═══════════════════════════════════════");
            LOG_MSG("RESET", "  FACTORY RESET — Xóa cấu hình!");
            LOG_MSG("RESET", "═══════════════════════════════════════");

            oled_showStatus("FACTORY RESET!");

            // LED nhấp nháy nhanh báo reset
            for (int i = 0; i < 10; i++) {
                digitalWrite(LED_STATUS_PIN, i % 2);
                delay(100);
            }

            nvs_clearConfig();
            delay(1000);
            ESP.restart();
        }
    }
}

// ===== Flush buffer → HTTP POST =====
void flushBufferToServer() {
    uint8_t count = buffer_count();
    if (count == 0) return;

    // Chỉ gửi khi có WiFi
    if (!wifi_isConnected()) {
        LOG_MSG("GATEWAY", "⚠ Chưa có WiFi, giữ gói tin trong buffer.");
        return;
    }

    // Lấy tất cả gói ra khỏi buffer
    BufferedPacket packets[PACKET_BUFFER_SIZE];
    uint8_t flushed = buffer_flush(packets, PACKET_BUFFER_SIZE);

    LOG_SEPARATOR();
    LOG_INFO("GATEWAY", "Flush %d gói tin → Server", flushed);

    // Hiển thị chi tiết từng gói
    for (uint8_t i = 0; i < flushed; i++) {
        const SensorPayload* p = &packets[i].payload;
        const char* typeStr = (p->pktType == PKT_TYPE_DATA) ? "DATA" :
                              (p->pktType == PKT_TYPE_HEARTBEAT) ? "HB" : "ERR";

        LOG_INFO("GATEWAY", "  [%d] Node:0x%02X Type:%s MsgID:%d RSSI:%d dBm",
                  i + 1, p->nodeId, typeStr, p->msgId, packets[i].rssi);
    }

    // LED nhấp nháy = đang gửi
    digitalWrite(LED_STATUS_PIN, HIGH);
    oled_showStatus("Sending...");

    bool success = http_sendBatch(packets, flushed);

    digitalWrite(LED_STATUS_PIN, LOW);

    if (!success) {
        // Gửi thất bại → đẩy lại vào buffer (nếu còn chỗ)
        LOG_MSG("GATEWAY", "⚠ Gửi thất bại! Đẩy lại gói tin vào buffer...");
        for (uint8_t i = 0; i < flushed; i++) {
            if (!buffer_push(&packets[i].payload, packets[i].rssi)) {
                LOG_INFO("GATEWAY", "🔴 Mất gói tin Node:0x%02X MsgID:%d (buffer đầy)",
                          packets[i].payload.nodeId, packets[i].payload.msgId);
            }
        }
    }

    LOG_SEPARATOR();
}

// ===== Setup =====
void setup() {
    Serial.begin(115200);
    delay(1000);

    // Nút BOOT cho factory reset
    pinMode(RESET_BUTTON_PIN, INPUT_PULLUP);

    // ── 1. Đọc cấu hình từ NVS ──
    nvs_loadConfig();

    // ── 2. Khởi tạo OLED (trước provisioning check) ──
    oled_init();

    // ── 3. Tải WiFi store ──
    wifi_store_load();

    // ── 4. Migration: chuyển WiFi cũ từ NVS sang wifi_store ──
    if (strlen(cfg_wifiSsid) > 0) {
        LOG_INFO("MAIN", "Migration: chuyển WiFi '%s' từ NVS cũ sang WiFi Store", cfg_wifiSsid);
        wifi_store_add(cfg_wifiSsid, cfg_wifiPassword);
        // Xóa WiFi khỏi NVS cũ (lưu lại config không có WiFi)
        nvs_saveGatewayConfig(cfg_gatewayId, "", "", cfg_serverBase, cfg_provisionKey);
        cfg_wifiSsid[0] = '\0';
        cfg_wifiPassword[0] = '\0';
    }

    // ── 5. Kiểm tra đã provisioned chưa ──
    if (!nvs_isProvisioned()) {
        // ═══ CHẾ ĐỘ PROVISIONING ═══
        // Hàm này blocking — không return cho đến khi ESP reboot
        startCaptivePortal();
        return;  // Không bao giờ đến đây
    }

    // ═══ CHẾ ĐỘ BÌNH THƯỜNG ═══
    Serial.println();
    Serial.println("========================================");
    Serial.println("  AIR QUALITY GATEWAY (Superloop)");
    Serial.printf("  Gateway ID : %s\n", cfg_gatewayId);
    Serial.printf("  LoRa       : AS32-TTL-100 (UART %d baud)\n", LORA_BAUD);
    Serial.printf("  API Server : %s\n", cfg_apiUrl);
    Serial.printf("  WiFi Store : %d mạng đã lưu\n", wifi_store_count());
    Serial.printf("  Flush      : Mỗi %d giây hoặc buffer đầy (%d gói)\n",
                  FLUSH_INTERVAL_MS / 1000, PACKET_BUFFER_SIZE);
    Serial.println("========================================");
    Serial.println();

    // 1. LED
    led_init();

    // 2. OLED Boot Screen
    oled_showBoot();

    // 3. Packet Buffer
    buffer_init();

    // 4. WiFi — Auto-connect từ WiFi Store
    Serial.println("[1/3] Auto-connect WiFi...");
    oled_showStatus("WiFi scanning...");
    if (!wifi_autoConnect()) {
        Serial.println("[WARN] Không tìm được WiFi đã lưu.");
        oled_showStatus("No WiFi found!");

        // Nếu có WiFi trong store nhưng không kết nối được → thử lại trong loop
        // Nếu không có WiFi nào → vào Captive Portal để cấu hình
        if (wifi_store_count() == 0) {
            Serial.println("[INFO] Chưa có WiFi nào → vào Captive Portal...");
            startCaptivePortal();
            return;
        }
        Serial.println("[INFO] Sẽ thử kết nối lại trong loop.");
    }

    // 5. LoRa Receiver
    Serial.println("[2/3] Khởi tạo LoRa Receiver...");
    oled_showStatus("LoRa init...");
    if (!lora_rx_init()) {
        oled_showStatus("LoRa FAILED!");
        Serial.println("[ERROR] LoRa THẤT BẠI! Restart...");
        delay(3000);
        esp_restart();
    }

    Serial.println("[3/3] Setup hoàn tất!");
    Serial.println();
    Serial.println("========================================");
    Serial.println("  [OK] Gateway đang hoạt động!");
    Serial.println("  Chờ nhận gói tin LoRa từ Sensor Node...");
    Serial.printf("  Giữ nút BOOT %d giây để Factory Reset\n", RESET_HOLD_TIME_MS / 1000);
    Serial.println("========================================");
    Serial.println();

    lastFlushTime = millis();
    lastHeartbeatTime = 0;  // Gửi heartbeat ngay lần loop đầu tiên
}

// ===== Main Loop (Superloop) =====
void loop() {
    // 0. Factory Reset check
    checkFactoryReset();

    // 1. WiFi: auto-reconnect nếu mất
    wifi_reconnectIfNeeded();

    // 2. LoRa: poll UART để nhận gói tin
    lora_rx_poll();

    // 3. Kiểm tra điều kiện flush buffer → HTTP POST
    bool shouldFlush = false;

    // Điều kiện 1: Buffer đầy
    if (buffer_isFull()) {
        LOG_MSG("GATEWAY", "Buffer đầy → Flush ngay!");
        shouldFlush = true;
    }

    // Điều kiện 2: Đã qua FLUSH_INTERVAL_MS kể từ lần flush cuối VÀ có data
    if (!shouldFlush && buffer_count() > 0) {
        if (millis() - lastFlushTime >= FLUSH_INTERVAL_MS) {
            LOG_MSG("GATEWAY", "Timeout → Flush buffer.");
            shouldFlush = true;
        }
    }

    if (shouldFlush) {
        flushBufferToServer();
        lastFlushTime = millis();
    }

    // 4. Heartbeat — gửi định kỳ để server biết gateway còn sống
    if (wifi_isConnected() && (lastHeartbeatTime == 0 || millis() - lastHeartbeatTime >= HEARTBEAT_INTERVAL_MS)) {
        http_sendHeartbeat();
        lastHeartbeatTime = millis();
    }

    // 5. Cập nhật LED
    led_update();

    // 6. Cập nhật OLED
    oled_update();

    // 7. Yield cho WiFi stack
    delay(50);  // 50ms — đủ nhanh để không miss gói LoRa UART
}
