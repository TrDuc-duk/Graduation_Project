#pragma once
#include <stdbool.h>
#include <stdint.h>

// =============================================================================
//  WIFI STORE — Lưu/đọc danh sách WiFi credentials từ NVS
//  Tối đa 5 WiFi, mỗi WiFi gồm SSID + Password
// =============================================================================

#define WIFI_STORE_MAX 5

struct WifiCredential {
    char ssid[64];
    char password[64];
};

/**
 * Đọc danh sách WiFi đã lưu từ NVS vào RAM
 * Gọi 1 lần trong setup()
 */
void wifi_store_load();

/**
 * Số lượng WiFi đã lưu
 */
uint8_t wifi_store_count();

/**
 * Lấy toàn bộ danh sách WiFi credentials
 */
const WifiCredential* wifi_store_getAll();

/**
 * Thêm hoặc cập nhật WiFi credential
 * Nếu SSID đã tồn tại → cập nhật password
 * Nếu đầy (5 mạng) → xóa mạng cũ nhất (slot 0) và đẩy lên
 * @return true nếu lưu thành công
 */
bool wifi_store_add(const char* ssid, const char* password);

/**
 * Xóa toàn bộ WiFi credentials (factory reset)
 */
void wifi_store_clear();
