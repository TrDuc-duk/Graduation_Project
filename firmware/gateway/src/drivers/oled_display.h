#pragma once
#include <stdbool.h>
#include <stdint.h>

// =============================================================================
//  OLED DISPLAY DRIVER — SSD1306 128×64 I2C
//  Hiển thị trạng thái Gateway realtime trên màn hình OLED
// =============================================================================

/**
 * Khởi tạo OLED display (I2C + SSD1306)
 * @return true nếu khởi tạo thành công
 */
bool oled_init();

/**
 * Hiển thị Boot Screen (Gateway ID + firmware info)
 * Gọi 1 lần trong setup(), blocking ~2 giây
 */
void oled_showBoot();

/**
 * Hiển thị Provisioning Mode (WiFi AP info)
 * Gọi khi vào chế độ Captive Portal
 */
void oled_showProvisioning();

/**
 * Cập nhật màn hình Normal Mode (WiFi, LoRa stats, buffer, uptime)
 * Gọi trong loop() — tự throttle theo OLED_UPDATE_MS
 */
void oled_update();

/**
 * Cập nhật thông tin gói cuối cùng nhận được (gọi từ lora_receiver)
 */
void oled_setLastPacket(uint8_t nodeId, uint8_t pktType);

/**
 * Hiển thị 1 dòng trạng thái tạm ở cuối màn hình
 * VD: "Sending...", "FACTORY RESET!"
 * Sẽ bị ghi đè bởi oled_update() tiếp theo
 */
void oled_showStatus(const char* msg);
