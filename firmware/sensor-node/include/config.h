#pragma once

// =============================================================================
//  SENSOR NODE CONFIGURATION
//  Air Quality Monitoring System - FreeRTOS Firmware
//
//  CHÚ Ý: Chỉ chứa PIN MAPPING và hằng số phần cứng.
//  NODE_ID được cấu hình qua Captive Portal và lưu trong NVS.
// =============================================================================

// ===== LoRa AS32-TTL-100 (UART) =====
// Dùng Serial1 (remap GPIO32/33) vì Serial2 đã dùng cho PMS7003
#define LORA_UART_NUM 1 // HardwareSerial(1)
#define LORA_RX_PIN 32  // ESP32 RX ← Module TXD
#define LORA_TX_PIN 33  // ESP32 TX → Module RXD
#define LORA_MD0_PIN 25 // Mode bit 0
#define LORA_MD1_PIN 26 // Mode bit 1
#define LORA_AUX_PIN 27 // AUX (LOW = module đang bận)
#define LORA_BAUD 9600  // UART baud rate (mặc định AS32)

// ===== PMS7003 UART Pins =====
#define PMS_RX_PIN 16  // ESP32 RX2 ← PMS7003 TX
#define PMS_TX_PIN 17  // ESP32 TX2 → PMS7003 RX
#define PMS_SET_PIN 15 // PMS7003 SET pin (HIGH=active, LOW=sleep)

// ===== CCS811 I2C =====
#define CCS811_SDA_PIN 21 // I2C Data
#define CCS811_SCL_PIN 22 // I2C Clock
#define CCS811_ADDR 0x5A  // I2C Address (ADDR pin = LOW)

// ===== DHT22 =====
#define DHT_PIN 4      // Data pin (GPIO4)
#define DHT_TYPE DHT22 // Sensor type

// ===== Battery ADC =====
#define BATTERY_ADC_PIN 34     // ADC1_CH6 (voltage divider: 2×100KΩ)
#define BATTERY_SAMPLES 16     // Số lần đọc ADC lấy trung bình
#define BATTERY_V_MAX 3.81f    // Điện áp pin 18650 đầy (dưới tải)
#define BATTERY_V_MIN 3.0f     // Điện áp pin 18650 hết
#define BATTERY_V_DIVIDER 2.0f // Hệ số voltage divider (R1=R2=100K)

// ===== OLED Display (SSD1306 128×64, I2C trên Wire1) =====
#define OLED_SDA_PIN     5    // I2C SDA (Wire1, tách biệt CCS811)
#define OLED_SCL_PIN     18   // I2C SCL (Wire1, tách biệt CCS811)
#define OLED_UPDATE_MS   1000 // Cập nhật OLED mỗi 1 giây

// ===== Timing =====
#define SEND_INTERVAL_MS 15000          // 15 giây (test mode, production: 300000)
#define PMS_WARMUP_MS 5000            // PMS7003 warm-up 30 giây
#define CCS811_WARMUP_MS 1200000       // CCS811 warm-up 20 phút (lần đầu bật)
#define SENSOR_READ_RETRIES 3          // Số lần retry khi đọc sensor lỗi
#define BATTERY_READ_INTERVAL_MS 30000 // Đọc pin mỗi 30 giây

// ===== FreeRTOS Task Config =====
#define SENSOR_TASK_STACK 4096
#define SENSOR_TASK_PRIORITY 2 // Cao — đọc sensor là nhiệm vụ chính
#define SENSOR_TASK_CORE 0     // Core 0

#define LORA_TASK_STACK 2048
#define LORA_TASK_PRIORITY 3 // Cao nhất — gửi xong sớm để sleep module
#define LORA_TASK_CORE 1     // Core 1 riêng (không bị sensor block)

#define BATTERY_TASK_STACK 2048
#define BATTERY_TASK_PRIORITY 1 // Thấp — đọc pin không quan trọng bằng
#define BATTERY_TASK_CORE 0     // Core 0

#define WDT_TASK_STACK 2048
#define WDT_TASK_PRIORITY 0 // Thấp nhất
#define WDT_TASK_CORE 0     // Core 0

#define DATA_QUEUE_SIZE 3     // Buffer 3 gói tin nếu LoRa đang bận
#define WDT_TIMEOUT_MS 60000  // 1 phút không heartbeat → reset ESP32 (> SEND_INTERVAL)

// ===== Server & Provisioning (cấu hình cứng) =====
#include "secrets.h"  // SERVER_BASE_URL, PROVISION_KEY: chép secrets.example.h thành secrets.h rồi điền (không commit)

// ===== Factory Reset =====
#define RESET_BUTTON_PIN 0       // Nút BOOT (GPIO0)
#define RESET_HOLD_TIME_MS 5000  // Giữ 5 giây để factory reset

// ===== Provisioning LED =====
#define LED_PROVISION_PIN 2      // LED tích hợp trên ESP32 DevKit (GPIO2)
