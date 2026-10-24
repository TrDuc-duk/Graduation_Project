#pragma once

// =============================================================================
//  SENSOR NODE CONFIGURATION — DEEP-SLEEP VERSION
//  ESP32 DOIT DevKit V1 (30 chân) + LoRa AS32-TTL-100 + PMS7003 + CCS811 + AHT10
//
//  Kiến trúc: setup() → đo → gửi LoRa → esp_deep_sleep()
//  KHÔNG dùng FreeRTOS tasks
// =============================================================================

// ===== LoRa AS32-TTL-100 (UART) =====
#define LORA_UART_NUM 1
#define LORA_RX_PIN 16
#define LORA_TX_PIN 17
#define LORA_MD0_PIN 4
#define LORA_MD1_PIN 5
#define LORA_BAUD 9600

// ===== PMS7003 UART Pins =====
#define PMS_RX_PIN 25
#define PMS_TX_PIN 26

// ===== CCS811 I2C =====
#define CCS811_SDA_PIN 21
#define CCS811_SCL_PIN 22
#define CCS811_ADDR 0x5A
#define CCS811_WAK_PIN 23
#define CCS811_ADD_PIN 18

// ===== AHT10 =====
#define AHT10_ADDR 0x38

// ===== Battery ADC =====
#define BATTERY_ADC_PIN 15
#define BATTERY_SAMPLES 16
#define BATTERY_V_MAX 3.81f
#define BATTERY_V_MIN 3.0f
#define BATTERY_V_DIVIDER 2.0f

// ===== OLED Display (SSD1306 128×64, I2C chung bus Wire) =====
#define OLED_SDA_PIN 21
#define OLED_SCL_PIN 22

// ===== Deep-Sleep Timing =====
#define DEEP_SLEEP_US 1800000000ULL // 30 phút (µs) — thay đổi ở đây
#define PMS_WARMUP_MS 30000         // PMS7003 warm-up 30 giây (đúng datasheet)
#define SENSOR_READ_RETRIES 3       // Số lần retry khi đọc sensor lỗi

// ===== OLED Button Display =====
#define OLED_DISPLAY_DURATION_MS 10000 // Hiển thị OLED 10 giây khi nhấn nút
#define BUTTON_PIN 0                   // Nút BOOT (GPIO0)

// ===== Factory Reset =====
#define RESET_BUTTON_PIN 0
#define RESET_HOLD_TIME_MS 5000

// ===== Provisioning =====
#define LED_PROVISION_PIN 2
#include "secrets.h"  // SERVER_BASE_URL, PROVISION_KEY: chép secrets.example.h thành secrets.h rồi điền (không commit)
