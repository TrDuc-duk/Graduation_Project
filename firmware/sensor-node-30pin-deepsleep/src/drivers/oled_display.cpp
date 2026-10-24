#include "oled_display.h"
#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

#include "config.h"
#include "common/debug.h"
#include "core/nvs_config.h"

// =============================================================================
//  OLED DISPLAY — Deep-Sleep Version
//  SSD1306 128×64 I2C (Wire, chung bus với CCS811 và AHT10)
//  Mặc định TẮT. Chỉ bật khi cần (provisioning, nhấn nút).
// =============================================================================

static Adafruit_SSD1306 display(128, 64, &Wire, -1);
static bool oledReady = false;

// Dữ liệu sensor
static SensorPayload sensorData;
static bool hasSensorData = false;
static bool loraOk = false;

bool oled_init() {
    if (!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
        LOG_MSG("OLED", "❌ Không tìm thấy SSD1306!");
        return false;
    }

    oledReady = true;
    display.setRotation(2);  // Xoay 180°
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);
    display.display();

    LOG_INFO("OLED", "Khởi tạo OK! (SSD1306 128x64, Wire SDA=%d SCL=%d)",
             OLED_SDA_PIN, OLED_SCL_PIN);
    return true;
}

void oled_showBoot() {
    if (!oledReady) return;

    display.clearDisplay();
    display.setTextSize(1);

    display.setCursor(4, 4);
    display.print("AIR QUALITY SENSOR");

    display.drawLine(0, 16, 127, 16, SSD1306_WHITE);

    display.setTextSize(2);
    char idBuf[12];
    snprintf(idBuf, sizeof(idBuf), "N:0x%02X", cfg_nodeId);
    int16_t x = (128 - strlen(idBuf) * 12) / 2;
    if (x < 0) x = 0;
    display.setCursor(x, 24);
    display.print(idBuf);

    display.setTextSize(1);
    display.setCursor(10, 48);
    display.print("DeepSleep v1.0.0");

    display.display();
    delay(2000);
}

void oled_showProvisioning() {
    if (!oledReady) return;

    display.clearDisplay();
    display.setTextSize(1);

    display.setCursor(10, 0);
    display.print("=== SETUP MODE ===");

    display.setCursor(0, 18);
    display.print("WiFi:");
    display.setCursor(0, 28);
    display.print(" AirQuality-SN-Setup");

    display.setCursor(0, 40);
    display.print("Connect & open:");
    display.setCursor(0, 52);
    display.print(" 192.168.4.1");

    display.display();
}

void oled_showData() {
    if (!oledReady) return;

    display.clearDisplay();
    display.setTextSize(1);

    // ── Dòng 1: Node ID + LoRa + Battery ──
    display.setCursor(0, 0);
    display.printf("N:%02X", cfg_nodeId);

    display.setCursor(40, 0);
    display.print(loraOk ? "LoRa:OK" : "LoRa:--");

    display.setCursor(92, 0);
    display.printf("B:%d%%", sensorData.battery);

    display.drawLine(0, 10, 127, 10, SSD1306_WHITE);

    if (hasSensorData) {
        // PM Data
        display.setCursor(0, 13);
        if (sensorData.pm1 != SENSOR_ERROR_U16)
            display.printf("PM1 : %.1f", sensorData.pm1 / 10.0f);
        else
            display.print("PM1 : ---");

        display.setCursor(0, 23);
        if (sensorData.pm25 != SENSOR_ERROR_U16)
            display.printf("PM25: %.1f", sensorData.pm25 / 10.0f);
        else
            display.print("PM25: ---");

        display.setCursor(0, 33);
        if (sensorData.pm10 != SENSOR_ERROR_U16)
            display.printf("PM10: %.1f", sensorData.pm10 / 10.0f);
        else
            display.print("PM10: ---");

        display.drawLine(0, 43, 127, 43, SSD1306_WHITE);

        // CO2 + TVOC
        display.setCursor(0, 46);
        display.printf("CO2:%-5u TVOC:%u",
                       sensorData.co2, sensorData.tvoc);

        // Temp + Humidity
        display.setCursor(0, 56);
        if (sensorData.temperature != SENSOR_ERROR_I16)
            display.printf("T:%.1fC", sensorData.temperature / 10.0f);
        else
            display.print("T:---");

        display.setCursor(64, 56);
        if (sensorData.humidity != SENSOR_ERROR_U16)
            display.printf("H:%.1f%%", sensorData.humidity / 10.0f);
        else
            display.print("H:---");
    } else {
        display.setCursor(16, 30);
        display.print("No data");
    }

    display.display();
}

void oled_setSensorData(const SensorPayload* data) {
    memcpy(&sensorData, data, sizeof(SensorPayload));
    hasSensorData = true;
}

void oled_setLoRaStatus(bool success) {
    loraOk = success;
}

void oled_sleep() {
    if (!oledReady) return;
    display.ssd1306_command(SSD1306_DISPLAYOFF);
}

void oled_wake() {
    if (!oledReady) return;
    display.ssd1306_command(SSD1306_DISPLAYON);
}
