#include "lora_task.h"
#include <Arduino.h>
#include "config.h"
#include "common/debug.h"
#include "common/packet.h"
#include "rtos/shared.h"
#include "core/nvs_config.h"
#include "drivers/lora_radio.h"
#include "drivers/oled_display.h"

// =============================================================================
//  LORA TASK IMPLEMENTATION
//  - Chờ data từ Queue (event-driven, không polling)
//  - Gửi xong → đưa LoRa module vào sleep mode
//  - Nếu timeout 10 phút không có data → gửi Heartbeat
// =============================================================================

#define LORA_QUEUE_TIMEOUT_MS  600000  // 10 phút timeout tổng
#define LORA_SEND_RETRIES      2       // Số lần retry gửi LoRa
#define LORA_HB_CHUNK_MS       30000   // 30 giây mỗi lần chờ Queue (cập nhật heartbeat)

void loraTask(void* parameter) {
    SensorPayload rxPayload;

    LOG_INFO("TASK", "LoRaTask started (Core %d)", xPortGetCoreID());

    while (true) {
        // ── Heartbeat cho WatchdogTask ──
        taskHeartbeat[TASK_LORA] = xTaskGetTickCount();

        // Block chờ data từ SensorTask (Queue)
        // Chia timeout thành các chunk nhỏ để cập nhật heartbeat
        bool received = false;
        uint32_t waitRemaining = LORA_QUEUE_TIMEOUT_MS;

        while (waitRemaining > 0) {
            uint32_t thisWait = (waitRemaining > LORA_HB_CHUNK_MS) ? LORA_HB_CHUNK_MS : waitRemaining;

            if (xQueueReceive(dataQueue, &rxPayload, pdMS_TO_TICKS(thisWait)) == pdTRUE) {
                received = true;
                break;
            }

            waitRemaining -= thisWait;
            taskHeartbeat[TASK_LORA] = xTaskGetTickCount();  // Heartbeat
        }

        if (received) {
            // ═══ Nhận được data → gửi LoRa ═══
            bool sent = false;
            oled_showStatus("Sending...");

            for (int attempt = 1; attempt <= LORA_SEND_RETRIES; attempt++) {
                if (lora_sendPacket(&rxPayload)) {
                    sent = true;
                    LOG_INFO("LoRa TX", "MsgID:%d PM1:%.1f PM2.5:%.1f PM10:%.1f CO2:%d TVOC:%d T:%.1f H:%.1f Bat:%d%%",
                        rxPayload.msgId,
                        rxPayload.pm1  == SENSOR_ERROR_U16 ? -1.0f : rxPayload.pm1  / 10.0f,
                        rxPayload.pm25 == SENSOR_ERROR_U16 ? -1.0f : rxPayload.pm25 / 10.0f,
                        rxPayload.pm10 == SENSOR_ERROR_U16 ? -1.0f : rxPayload.pm10 / 10.0f,
                        rxPayload.co2, rxPayload.tvoc,
                        rxPayload.temperature == SENSOR_ERROR_I16 ? -99.9f : rxPayload.temperature / 10.0f,
                        rxPayload.humidity == SENSOR_ERROR_U16 ? -1.0f : rxPayload.humidity / 10.0f,
                        rxPayload.battery);
                    break;
                }
                LOG_INFO("LoRa TX", "Gửi lỗi, thử lại %d/%d", attempt, LORA_SEND_RETRIES);
                vTaskDelay(pdMS_TO_TICKS(500));
            }

            oled_setLoRaStatus(sent);
            oled_showStatus(sent ? "TX OK" : "TX FAIL");

            if (!sent) {
                LOG_INFO("LoRa TX", "Gửi THẤT BẠI sau %d lần thử! Bỏ gói tin.", LORA_SEND_RETRIES);
            }

        } else {
            // ═══ Timeout → gửi Heartbeat ═══
            SensorPayload heartbeat;
            memset(&heartbeat, 0, sizeof(SensorPayload));
            heartbeat.nodeId  = cfg_nodeId;
            heartbeat.pktType = PKT_TYPE_HEARTBEAT;
            heartbeat.msgId   = msgCounter++;
            heartbeat.battery = batteryLevel;

            if (lora_sendPacket(&heartbeat)) {
                LOG_INFO("LoRa TX", "Heartbeat sent (Bat: %d%%)", heartbeat.battery);
            } else {
                LOG_MSG("LoRa TX", "⚠ Heartbeat gửi thất bại!");
            }
        }

        // Đưa LoRa module vào sleep mode sau khi gửi xong
        lora_sleep();
    }
}
