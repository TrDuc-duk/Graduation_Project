#pragma once

// =============================================================================
//  SENSOR NODE CONFIGURATION (ESP32 30-pin / DOIT DevKit V1)
//  Air Quality Monitoring System - FreeRTOS Firmware
//
//  CHÚ Ý: Chỉ chứa PIN MAPPING và hằng số phần cứng.
//  NODE_ID được cấu hình qua Captive Portal và lưu trong NVS.
//
//  Board: ESP32 DOIT DevKit V1 (30 chân)
//  Pin mapping theo mạch AirMonitorModule
// =============================================================================

// ===== LoRa AS32-TTL-100 (UART) =====
// Dùng Serial1 (GPIO16/17) — giống AirMonitorModule
#define LORA_UART_NUM 1 // HardwareSerial(1)
#define LORA_RX_PIN 16  // ESP32 RX ← Module TXD
#define LORA_TX_PIN 17  // ESP32 TX → Module RXD
#define LORA_MD0_PIN 4  // Mode bit 0
#define LORA_MD1_PIN 5  // Mode bit 1
#define LORA_BAUD 9600  // UART baud rate (mặc định AS32)

// ===== PMS7003 UART Pins =====
#define PMS_RX_PIN 25  // ESP32 RX ← PMS7003 TX (dùng chân khác LoRa)
#define PMS_TX_PIN 26  // ESP32 TX → PMS7003 RX

// ===== CCS811 I2C =====
// Giữ cùng tốc độ trên bus I2C dùng chung với OLED và AHT10.
#define I2C_CLOCK_HZ 10000UL
#define CCS811_SDA_PIN 21 // I2C Data (chung bus Wire với OLED)
#define CCS811_SCL_PIN 22 // I2C Clock
#define CCS811_ADDR 0x5A  // I2C Address (ADDR pin = LOW)
#define CCS811_WAK_PIN 23 // Wake pin (LOW = active)
#define CCS811_ADD_PIN 18 // Address select pin (LOW = 0x5A)

// ===== AHT10 (thay thế DHT22) =====
// AHT10 dùng I2C, chung bus Wire với CCS811 và OLED
#define AHT10_ADDR 0x38   // I2C Address mặc định
// Dùng chung SDA=21, SCL=22

// ===== Battery ADC =====
#define BATTERY_ADC_PIN 15     // ADC pin (voltage divider)
#define BATTERY_SAMPLES 16     // Số lần đọc ADC lấy trung bình
#define BATTERY_V_MAX 3.81f    // Điện áp pin 18650 đầy (dưới tải)
#define BATTERY_V_MIN 3.0f     // Điện áp pin 18650 hết
#define BATTERY_V_DIVIDER 2.0f // Hệ số voltage divider (R1=R2=100K)

// ===== OLED Display (SSD1306 128×64, I2C chung bus Wire) =====
// Board 30 chân: OLED dùng chung bus Wire (SDA=21, SCL=22) với CCS811 và AHT10
#define OLED_SDA_PIN     21
#define OLED_SCL_PIN     22
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
