#pragma once
#include <stdint.h>
#include <stdbool.h>

// =============================================================================
//  LORA RECEIVER DRIVER - AS32-TTL-100 (UART)
//  Nhận gói tin từ Sensor Node qua UART transparent mode
//  Gateway poll UART trong loop() để đọc data
// =============================================================================

/**
 * Khởi tạo LoRa receiver (UART + MD0/MD1 Normal mode)
 * @return true nếu khởi tạo thành công (AUX HIGH)
 */
bool lora_rx_init();

/**
 * Kiểm tra và xử lý dữ liệu nhận từ UART
 * Gọi trong loop() — nếu có đủ 18 bytes → parse → push vào buffer
 * Non-blocking
 */
void lora_rx_poll();

/**
 * Lấy tổng số gói đã nhận thành công
 */
uint32_t lora_rx_getPacketCount();

/**
 * Lấy tổng số gói bị lỗi (kích thước sai, etc.)
 */
uint32_t lora_rx_getErrorCount();
