#include "oled_display.h"
#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#include "config.h"
#include "common/debug.h"
#include "core/nvs_config.h"
#include "drivers/wifi_manager.h"
#include "drivers/lora_receiver.h"
#include "core/packet_buffer.h"

// =============================================================================
//  OLED DISPLAY IMPLEMENTATION — SSD1306 128×64 I2C
// =============================================================================

static Adafruit_SSD1306 display(128, 64, &Wire, -1);
static bool oledReady = false;
static unsigned long lastUpdateTime = 0;

// Lưu thông tin gói cuối cùng nhận được (để hiển thị)
static uint8_t  lastNodeId   = 0;
static uint8_t  lastPktType  = 0;

bool oled_init() {
    Wire.begin(OLED_SDA_PIN, OLED_SCL_PIN);

    if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
        LOG_MSG("OLED", "❌ Không tìm thấy SSD1306! Kiểm tra kết nối I2C.");
        return false;
    }

    oledReady = true;
    display.setRotation(2);  // Xoay màn hình 180°
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);
    display.display();

    LOG_MSG("OLED", "✅ Khởi tạo OK! (SSD1306 128x64, I2C)");
    return true;
}

void oled_showBoot() {
    if (!oledReady) return;

    display.clearDisplay();
    display.setTextSize(1);

    // Dòng 1: Title
    display.setCursor(4, 4);
    display.print("AIR QUALITY GATEWAY");

    // Dòng 2: Separator
    display.drawLine(0, 16, 127, 16, SSD1306_WHITE);

    // Dòng 3-4: Gateway ID (text size 2 = lớn hơn)
    display.setTextSize(2);
    // Tính vị trí căn giữa
    int16_t gwLen = strlen(cfg_gatewayId);
    int16_t x = (128 - gwLen * 12) / 2;
    if (x < 0) x = 0;
    display.setCursor(x, 24);
    display.print(cfg_gatewayId);

    // Dòng 5: Version
    display.setTextSize(1);
    display.setCursor(22, 48);
    display.print("Firmware v1.0.0");

    display.display();

    delay(2000);
}

void oled_showProvisioning() {
    if (!oledReady) return;

    display.clearDisplay();
    display.setTextSize(1);

    // Title
    display.setCursor(10, 0);
    display.print("=== SETUP MODE ===");

    // WiFi AP info
    display.setCursor(0, 18);
    display.print("WiFi:");
    display.setCursor(0, 28);
    display.print(" AirQuality-GW-Setup");

    // Password
    display.setCursor(0, 40);
    display.print("Connect & open:");
    display.setCursor(0, 52);
    display.print(" 192.168.4.1");

    display.display();
}

void oled_update() {
    if (!oledReady) return;

    // Throttle: chỉ cập nhật mỗi OLED_UPDATE_MS
    unsigned long now = millis();
    if (now - lastUpdateTime < OLED_UPDATE_MS) return;
    lastUpdateTime = now;

    // Cập nhật thông tin gói cuối (được set bởi oled_setLastPacket)

    display.clearDisplay();
    display.setTextSize(1);

    // ── Dòng 1: Gateway ID + WiFi status ──
    display.setCursor(0, 0);
    display.print(cfg_gatewayId);

    if (wifi_isConnected()) {
        // Hiển thị "WiFi:" + tên WiFi đang kết nối
        const char* ssid = wifi_getSSID();
        char wifiBuf[22];
        snprintf(wifiBuf, sizeof(wifiBuf), "WiFi:%.15s", ssid);
        int16_t x = 128 - strlen(wifiBuf) * 6;
        if (x < 42) x = 42;
        display.setCursor(x, 0);
        display.print(wifiBuf);
    } else {
        display.setCursor(76, 0);
        display.print("WiFi:OFF");
    }

    // ── Dòng 2: IP Address ──
    display.setCursor(0, 10);
    display.print("IP:");
    display.print(wifi_isConnected() ? wifi_getIP() : "---");

    // ── Dòng 3: WiFi RSSI ──
    display.setCursor(0, 20);
    if (wifi_isConnected()) {
        display.printf("RSSI:%ddBm", wifi_getRSSI());
    } else {
        display.print("RSSI:---");
    }

    // ── Separator ──
    display.drawLine(0, 29, 127, 29, SSD1306_WHITE);

    // ── Dòng 4: LoRa RX stats ──
    display.setCursor(0, 32);
    display.printf("LoRa RX:%-5lu E:%lu",
                   lora_rx_getPacketCount(),
                   lora_rx_getErrorCount());

    // ── Dòng 5: Buffer status ──
    display.setCursor(0, 42);
    display.printf("Buffer: %d/%d",
                   buffer_count(), PACKET_BUFFER_SIZE);

    // ── Dòng 6: Last packet info ──
    display.setCursor(0, 52);
    if (lastNodeId > 0) {
        const char* typeStr = (lastPktType == 0x01) ? "DATA" :
                              (lastPktType == 0x02) ? "HB"   : "ERR";
        display.printf("Last:Node%02X %s", lastNodeId, typeStr);
    } else {
        display.print("Last: ---");
    }

    // ── Dòng 7 (phải): Uptime ──
    // Tính uptime
    unsigned long uptimeSec = now / 1000;
    unsigned long h = uptimeSec / 3600;
    unsigned long m = (uptimeSec % 3600) / 60;
    unsigned long s = uptimeSec % 60;

    // Hiển thị uptime bên phải dòng 5 (buffer)
    display.setCursor(80, 42);
    display.printf("Up:%02luh%02lu", h, m);

    display.display();
}

void oled_setLastPacket(uint8_t nodeId, uint8_t pktType) {
    lastNodeId  = nodeId;
    lastPktType = pktType;
}

void oled_showStatus(const char* msg) {
    if (!oledReady) return;

    // Xóa vùng dòng cuối (y=56..63) và hiển thị message
    display.fillRect(0, 52, 128, 12, SSD1306_BLACK);
    display.setTextSize(1);
    display.setCursor(0, 52);
    display.print(msg);
    display.display();
}
