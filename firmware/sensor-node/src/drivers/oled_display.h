#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "common/packet.h"

// =============================================================================
//  OLED DISPLAY DRIVER — SSD1306 128×64 I2C (Wire1)
//  Hiển thị trạng thái Sensor Node realtime trên màn hình OLED
//  Bus I2C riêng (Wire1, SDA=5, SCL=18), tách biệt CCS811
// =============================================================================

/**
 * Khởi tạo OLED display (Wire1 + SSD1306)
 * @return true nếu khởi tạo thành công
 */
bool oled_init();

/**
 * Hiển thị Boot Screen (Node ID + firmware info)
 * Gọi 1 lần trong setup(), blocking ~2 giây
 */
void oled_showBoot();

/**
 * Hiển thị Provisioning Mode (WiFi AP info)
 * Gọi khi vào chế độ Captive Portal
 */
void oled_showProvisioning();

/**
 * Cập nhật màn hình Normal Mode (sensor data, LoRa, battery)
 * Gọi trong loop hoặc task — tự throttle theo OLED_UPDATE_MS
 */
void oled_update();

/**
 * Cập nhật dữ liệu sensor để hiển thị (gọi từ sensor_task)
 */
void oled_setSensorData(const SensorPayload* data);

/**
 * Cập nhật trạng thái LoRa TX (gọi từ lora_task)
 * @param success true nếu gửi LoRa thành công lần cuối
 */
void oled_setLoRaStatus(bool success);

/**
 * Hiển thị 1 dòng trạng thái tạm ở cuối màn hình
 * VD: "Sending...", "FACTORY RESET!"
 * Sẽ bị ghi đè bởi oled_update() tiếp theo
 */
void oled_showStatus(const char* msg);
