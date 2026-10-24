#pragma once

// =============================================================================
//  CAPTIVE PORTAL — Gateway WiFi AP + Web Server cho Provisioning
//  Bật khi thiết bị chưa được cấu hình (lần đầu bật hoặc sau factory reset)
// =============================================================================

/**
 * Khởi động Captive Portal (blocking)
 * - Bật WiFi AP: "AirQuality-GW-Setup"
 * - DNS redirect tất cả domain → ESP32
 * - Phục vụ web form cấu hình
 * - Khi user nhấn Save: kết nối WiFi → đăng ký server → lưu NVS → reboot
 *
 * Hàm này KHÔNG RETURN cho đến khi provisioning hoàn tất (ESP sẽ reboot)
 */
void startCaptivePortal();
