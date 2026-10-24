/**
 * TEST: PMS7003 - Cảm biến bụi mịn PM2.5 / PM10
 * Giao tiếp: UART2 (RX=16, TX=17), SET pin (GPIO15)
 * 
 * Flash: pio run -e test_pms7003 -t upload && pio device monitor
 * 
 * PASS khi: Quạt quay khi SET=HIGH, PM2.5/PM10 > 0 sau warm-up
 * 
 * Chu kỳ test: Bật quạt → warm-up 30s → đọc 3 lần → tắt quạt → chờ 30s
 */

#include <Arduino.h>
#include <PMS.h>
#include "config.h"

static HardwareSerial pmsSerial(2);
static PMS pms(pmsSerial);
static PMS::DATA pmsData;

void setup() {
    Serial.begin(115200);
    delay(1000);

    Serial.println();
    Serial.println("========================================");
    Serial.println("  TEST: PMS7003 (PM2.5 / PM10)");
    Serial.printf("  UART: RX=%d, TX=%d\n", PMS_RX_PIN, PMS_TX_PIN);
    Serial.printf("  SET Pin: GPIO%d\n", PMS_SET_PIN);
    Serial.println("========================================");
    Serial.println();

    // Init UART2
    pmsSerial.begin(9600, SERIAL_8N1, PMS_RX_PIN, PMS_TX_PIN);
    Serial.println("[PMS7003] UART2 khởi tạo OK (9600 baud)");

    // Init SET pin
    pinMode(PMS_SET_PIN, OUTPUT);
    digitalWrite(PMS_SET_PIN, HIGH);
    Serial.printf("[PMS7003] SET pin (GPIO%d) = HIGH → Quạt chạy\n", PMS_SET_PIN);

    // Passive mode
    pms.passiveMode();
    Serial.println("[PMS7003] Chế độ: Passive (đọc khi yêu cầu)");

    Serial.println();
    Serial.println("[PMS7003] ✅ INIT OK!");
    Serial.println("[PMS7003] Bắt đầu chu kỳ test...");
    Serial.println();
}

static uint16_t cycleCount = 0;

void loop() {
    cycleCount++;

    // ═══ Bước 1: Bật quạt ═══
    Serial.println("══════════════════════════════════════");
    Serial.printf("  CHU KỲ #%d\n", cycleCount);
    Serial.println("══════════════════════════════════════");

    Serial.println("[PMS7003] Bật quạt (SET=HIGH, wakeUp)");
    digitalWrite(PMS_SET_PIN, HIGH);
    pms.wakeUp();

    // ═══ Bước 2: Warm-up 30 giây (đếm ngược) ═══
    Serial.printf("[PMS7003] Warm-up %d giây", PMS_WARMUP_MS / 1000);
    for (int i = PMS_WARMUP_MS / 1000; i > 0; i -= 5) {
        Serial.printf(".");
        delay(5000);
    }
    Serial.println(" OK!");

    // ═══ Bước 3: Đọc 3 lần liên tiếp ═══
    Serial.println();
    Serial.println("  #  │  PM1.0  │  PM2.5  │  PM10   │ Kết quả");
    Serial.println("─────────────────────────────────────────────");

    for (int i = 1; i <= 3; i++) {
        pms.requestRead();

        if (pms.readUntil(pmsData, 3000)) {
            uint16_t pm10_std  = pmsData.PM_AE_UG_1_0;
            uint16_t pm25_std  = pmsData.PM_AE_UG_2_5;
            uint16_t pm100_std = pmsData.PM_AE_UG_10_0;

            bool dataOk = (pm25_std > 0 || pm100_std > 0);
            const char* status = dataOk ? "✅ PASS" : "⚠ ZERO";

            Serial.printf("  %d  │ %3d µg  │ %3d µg  │ %3d µg  │ %s\n",
                           i, pm10_std, pm25_std, pm100_std, status);
        } else {
            Serial.printf("  %d  │  ERROR  │  ERROR  │  ERROR  │ ❌ FAIL\n", i);
        }

        delay(2000);
    }

    // ═══ Bước 4: Test SET pin (tắt quạt) ═══
    Serial.println();
    Serial.println("[PMS7003] Tắt quạt (sleep, SET=LOW)");
    pms.sleep();
    digitalWrite(PMS_SET_PIN, LOW);

    Serial.println("[PMS7003] → Kiểm tra: quạt phải NGỪNG quay");
    Serial.println("[PMS7003]   (Nếu quạt vẫn quay → SET pin chưa nối hoặc lỗi)");

    // Chờ 30 giây trước chu kỳ tiếp theo
    Serial.println();
    Serial.println("[PMS7003] Chờ 30 giây trước chu kỳ tiếp...");
    delay(30000);
}
