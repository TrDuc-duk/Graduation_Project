/**
 * TEST: CCS811 - Cảm biến CO2 / TVOC
 * Giao tiếp: I2C (SDA=21, SCL=22, Address=0x5A)
 * 
 * Flash: pio run -e test_ccs811 -t upload && pio device monitor
 * 
 * PASS khi: I2C scan tìm thấy 0x5A, đọc được CO2 >= 400 ppm
 * Lưu ý: Cần warm-up ~20 phút để dữ liệu chính xác
 */

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_CCS811.h>
#include "config.h"

static Adafruit_CCS811 ccs;
static unsigned long startTime = 0;

// ═══ I2C Bus Scanner ═══
void i2c_scan() {
    Serial.println("[I2C] Scanning bus (SDA=%d, SCL=%d)...");
    Serial.printf("[I2C] Scanning bus (SDA=%d, SCL=%d)...\n", CCS811_SDA_PIN, CCS811_SCL_PIN);

    int devicesFound = 0;
    for (uint8_t addr = 1; addr < 127; addr++) {
        Wire.beginTransmission(addr);
        if (Wire.endTransmission() == 0) {
            Serial.printf("  → Tìm thấy device tại 0x%02X", addr);
            if (addr == CCS811_ADDR) Serial.print(" ← CCS811");
            Serial.println();
            devicesFound++;
        }
    }

    if (devicesFound == 0) {
        Serial.println("[I2C] ❌ Không tìm thấy device nào!");
        Serial.println("  → Kiểm tra: dây SDA/SCL, pull-up 4.7K, nguồn 3.3V");
    } else {
        Serial.printf("[I2C] ✅ Tìm thấy %d device(s)\n", devicesFound);
    }
    Serial.println();
}

void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("========================================");
    Serial.println("  TEST: CCS811 (CO2 / TVOC)");
    Serial.printf("  I2C: SDA=%d, SCL=%d, Addr=0x%02X\n", CCS811_SDA_PIN, CCS811_SCL_PIN, CCS811_ADDR);
    Serial.println("========================================");
    Serial.println();

    // Bước 0: Wake CCS811 (nWAKE must be LOW for I2C to work)
    pinMode(CCS811_WAK_PIN, OUTPUT);
    pinMode(CCS811_ADD_PIN, OUTPUT);
    digitalWrite(CCS811_WAK_PIN, LOW);   // Wake sensor (active LOW)
    digitalWrite(CCS811_ADD_PIN, LOW);   // Address = 0x5A
    delay(200);  // Đợi CCS811 boot

    // Bước 1: Scan I2C bus
    Wire.begin(CCS811_SDA_PIN, CCS811_SCL_PIN);
    Wire.setClock(10000); // Hạ xung nhịp I2C xuống 10KHz
    Wire.setTimeOut(3000); // Tăng timeout I2C (fix clock stretching khi OLED chung bus)
    i2c_scan();

    // Bước 2: Init CCS811
    Serial.println("[CCS811] Khởi tạo...");
    if (!ccs.begin(CCS811_ADDR)) {
        Serial.println("[CCS811] ❌ INIT FAIL - Không tìm thấy sensor!");
        Serial.println("  → Kiểm tra: ADDR pin (LOW=0x5A, HIGH=0x5B), WAKE pin (nối GND)");
        Serial.println("  → Chương trình dừng ở đây.");
        while (true) delay(1000);
    }

    // Chờ sensor sẵn sàng
    Serial.println("[CCS811] Chờ sensor sẵn sàng...");
    while (!ccs.available()) {
        delay(100);
    }

    ccs.setDriveMode(CCS811_DRIVE_MODE_1SEC);
    startTime = millis();

    Serial.println("[CCS811] ✅ INIT OK!");
    Serial.println("[CCS811] ⚠ Cần warm-up 20 phút để dữ liệu chính xác");
    Serial.println();
    Serial.println("[CCS811] Bắt đầu đọc liên tục mỗi 2 giây...");
    Serial.println("──────────────────────────────────────────────────");
    Serial.println("  #  │  eCO2   │  eTVOC  │ Warm-up │ Kết quả");
    Serial.println("──────────────────────────────────────────────────");
}

static uint16_t readCount = 0;

void loop() {
    readCount++;

    if (ccs.available()) {
        uint8_t err = ccs.readData();
        if (err == 0) {
            uint16_t co2  = ccs.geteCO2();
            uint16_t tvoc = ccs.getTVOC();

            unsigned long elapsed = (millis() - startTime) / 1000;
            bool warmedUp = elapsed >= (CCS811_WARMUP_MS / 1000);

            const char* warmStatus = warmedUp ? "✅ OK " : "⏳ ...";

            // CO2 baseline là 400 ppm (ngoài trời)
            bool dataOk = (co2 >= 400 && co2 <= 8192);
            const char* result = dataOk ? "✅ PASS" : "⚠ CHECK";

            Serial.printf(" %3d │ %4d ppm│ %4d ppb│ %s %3lum │ %s\n",
                           readCount, co2, tvoc, warmStatus, elapsed / 60, result);
        } else {
            Serial.printf(" %3d │  ERROR  │  ERROR  │ err=%d   │ ❌ FAIL\n",
                           readCount, err);
        }
    } else {
        Serial.printf(" %3d │   ---   │   ---   │ not rdy │ ⏳ WAIT\n", readCount);
    }

    delay(2000);
}
