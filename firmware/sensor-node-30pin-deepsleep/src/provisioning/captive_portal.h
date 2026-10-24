#pragma once

// =============================================================================
//  CAPTIVE PORTAL — Sensor Node WiFi AP + Web Server cho Provisioning
//  Bật WiFi tạm thời để cấu hình, sau đó tắt và chuyển sang LoRa-only
// =============================================================================

/**
 * Khởi động Captive Portal (blocking)
 * - Bật WiFi AP: "AirQuality-Node-Setup"
 * - User cấu hình qua web: chọn WiFi → chọn Gateway → đặt tên
 * - Đăng ký node với server qua WiFi tạm
 * - Lưu NVS → TẮT WiFi → Reboot vào chế độ LoRa
 */
void startCaptivePortal();
