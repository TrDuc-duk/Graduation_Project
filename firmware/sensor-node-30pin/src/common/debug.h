#pragma once
#include <Arduino.h>

// =============================================================================
//  DEBUG LOGGING MACROS
//  Đổi tên sang LOG_* để tránh xung đột với DEBUG_PRINT trong DHT library
//  Sử dụng: LOG_INFO("Module", "Message %d", value);
//           LOG_MSG("Module", "Simple message");
// =============================================================================

#define DEBUG_ENABLED 1

#if DEBUG_ENABLED
    #define LOG_INFO(tag, fmt, ...) \
        Serial.printf("[%s] " fmt "\n", tag, ##__VA_ARGS__)

    #define LOG_MSG(tag, msg) \
        Serial.printf("[%s] %s\n", tag, msg)

    #define LOG_SEPARATOR() \
        Serial.println("────────────────────────────────────────")
#else
    #define LOG_INFO(tag, fmt, ...)
    #define LOG_MSG(tag, msg)
    #define LOG_SEPARATOR()
#endif
