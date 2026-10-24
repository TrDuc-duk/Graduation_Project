#pragma once
#include <stdbool.h>
#include <stdint.h>

// =============================================================================
//  WIFI MANAGER - Scan & Auto-connect từ WiFi Store + Reconnect
// =============================================================================

/**
 * Quét WiFi xung quanh, so sánh với danh sách đã lưu trong wifi_store,
 * thử kết nối WiFi có RSSI mạnh nhất trước.
 * @return true nếu kết nối thành công
 */
bool wifi_autoConnect();

/**
 * Kiểm tra kết nối WiFi hiện tại
 */
bool wifi_isConnected();

/**
 * Tự động kết nối lại nếu mất WiFi
 * Thử SSID hiện tại trước, nếu thất bại nhiều lần → wifi_autoConnect()
 * Gọi trong loop(), non-blocking (dùng millis timer)
 */
void wifi_reconnectIfNeeded();

/**
 * Lấy RSSI tín hiệu WiFi (dBm)
 */
int32_t wifi_getRSSI();

/**
 * Lấy IP address dạng String
 */
const char* wifi_getIP();

/**
 * Lấy tên WiFi đang kết nối (SSID)
 */
const char* wifi_getSSID();
