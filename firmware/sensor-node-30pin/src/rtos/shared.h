#pragma once
#include <Arduino.h>
#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>
#include <freertos/task.h>
#include <freertos/semphr.h>
#include "config.h"
#include "common/packet.h"

// =============================================================================
//  FREERTOS SHARED RESOURCES
//  Khai báo Queue, biến chia sẻ giữa các task
// =============================================================================

// --- Task IDs cho Watchdog ---
enum TaskId {
    TASK_SENSOR  = 0,
    TASK_LORA    = 1,
    TASK_BATTERY = 2,
    TASK_COUNT   = 3
};

// --- Shared variables (extern) ---
extern QueueHandle_t       dataQueue;          // SensorTask → LoRaTask
extern volatile uint8_t    batteryLevel;       // BatteryTask → SensorTask
extern volatile TickType_t taskHeartbeat[];    // Tất cả → WatchdogTask
extern SemaphoreHandle_t   i2cMutex;          // Bảo vệ bus I2C (Wire) giữa các task/core

// --- RTC Memory (survive deep sleep) ---
extern RTC_DATA_ATTR uint8_t msgCounter;

