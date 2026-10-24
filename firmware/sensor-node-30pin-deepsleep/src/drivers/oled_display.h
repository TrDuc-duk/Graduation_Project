#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "common/packet.h"

// =============================================================================
//  OLED DISPLAY DRIVER — SSD1306 128×64 I2C (Deep-Sleep Version)
//  Mặc định TẮT để tiết kiệm pin.
//  Chỉ bật khi nhấn nút hoặc provisioning mode.
// =============================================================================

/**
 * Khởi tạo OLED display (Wire + SSD1306)
 * @return true nếu khởi tạo thành công
 */
bool oled_init();

/**
 * Hiển thị Boot Screen (Node ID + firmware info)
 * Gọi 1 lần, blocking ~2 giây
 */
void oled_showBoot();

/**
 * Hiển thị Provisioning Mode (WiFi AP info)
 */
void oled_showProvisioning();

/**
 * Hiển thị sensor data lên OLED (gọi 1 lần mỗi chu kỳ)
 */
void oled_showData();

/**
 * Cập nhật dữ liệu sensor để hiển thị
 */
void oled_setSensorData(const SensorPayload* data);

/**
 * Cập nhật trạng thái LoRa TX
 */
void oled_setLoRaStatus(bool success);

/**
 * Tắt OLED (Display OFF)
 */
void oled_sleep();

/**
 * Bật OLED (Display ON)
 */
void oled_wake();
