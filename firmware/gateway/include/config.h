#pragma once

// =============================================================================
//  GATEWAY CONFIGURATION
//  Air Quality Monitoring System - Superloop Firmware
//
//  CHÚ Ý: Chỉ chứa PIN MAPPING và hằng số phần cứng.
//  Cấu hình runtime (WiFi, Server, Gateway ID) được lưu trong NVS
//  và thiết lập qua Captive Portal khi lần đầu bật.
// =============================================================================

// ===== LoRa AS32-TTL-100 (UART) — phải khớp cấu hình với Sensor Node =====
// Gateway dùng Serial2 (GPIO16/17) vì không có PMS7003
#define LORA_UART_NUM 2 // HardwareSerial(2)
#define LORA_RX_PIN 16  // ESP32 RX ← Module TXD
#define LORA_TX_PIN 17  // ESP32 TX → Module RXD
#define LORA_MD0_PIN 4  // Mode bit 0
#define LORA_MD1_PIN 5  // Mode bit 1
#define LORA_AUX_PIN 13 // AUX (LOW = module đang bận)
#define LORA_BAUD 9600  // UART baud rate (mặc định AS32)

// ===== Packet Buffer =====
#define PACKET_BUFFER_SIZE 10   // Tối đa 10 gói chờ gửi
#define FLUSH_INTERVAL_MS 30000 // Gửi HTTP mỗi 30 giây (hoặc khi buffer đầy)
#define HEARTBEAT_INTERVAL_MS 300000 // Gửi heartbeat mỗi 5 phút

// ===== Status LED =====
#define LED_WIFI_PIN 25   // LED WiFi (xanh = connected)
#define LED_STATUS_PIN 26 // LED trạng thái (nhấp nháy = đang gửi / provisioning)

// ===== WiFi Timing =====
#define WIFI_CONNECT_TIMEOUT_MS 15000 // Timeout kết nối lần đầu
#define WIFI_RETRY_DELAY_MS 5000      // Delay giữa các lần thử kết nối lại

// ===== HTTP =====
#define API_TIMEOUT_MS 10000 // HTTP request timeout
#define HTTP_RETRY_COUNT 3   // Số lần retry khi gửi thất bại

// ===== Server & Provisioning (cấu hình cứng) =====
#include "secrets.h"  // SERVER_BASE_URL, PROVISION_KEY, GATEWAY_SECRET: chép secrets.example.h thành secrets.h rồi điền (không commit)

// ===== OLED Display (SSD1306 128×64 I2C) =====
#define OLED_SDA_PIN     21   // I2C SDA (ESP32 default)
#define OLED_SCL_PIN     22   // I2C SCL (ESP32 default)
#define OLED_UPDATE_MS   1000 // Cập nhật OLED mỗi 1 giây

// ===== Factory Reset =====
#define RESET_BUTTON_PIN 0       // Nút BOOT (GPIO0) — giữ 5 giây để factory reset
#define RESET_HOLD_TIME_MS 5000  // Thời gian giữ nút để trigger reset
