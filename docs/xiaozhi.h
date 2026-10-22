#ifndef MCP_XIAOZHI_H
#define MCP_XIAOZHI_H

#include <WebSocketMCP.h>
#include <ArduinoJson.h>

// Khai báo các hàm ngoại lai từ file .ino chính để MCP có thể gọi được
extern void controlPump(bool state, int duration);
extern void controlLed(bool state);
extern float readTemperature();
extern float readHumidity();
extern float readSoilMoisture();
extern float getMoistureThreshold();
extern void setMoistureThreshold(float threshold);

// Khai báo client và Endpoint
WebSocketMCP mcpClient;
const char* mcpEndpoint = "your mcp_endpoint",
// Khai báo hàm trước khi sử dụng
void registerMcpTools();

// Callback kết nối MCP
void onMcpConnectionStatus(bool connected) {
    if (connected) {
        Serial.println("[MCP] ✅ Đã kết nối tới máy chủ Xiaozhi");
        registerMcpTools();
    } else {
        Serial.println("[MCP] ⚠️ Mất kết nối với máy chủ MCP");
    }
}

// Hàm đăng ký Tools
void registerMcpTools() {
    // 1. Tool điều khiển máy bơm
    mcpClient.registerTool(
        "pump_control",
        "Điều khiển máy bơm nước cho khu vườn",
        R"({
            "type": "object",
            "properties": {
                "state": { 
                    "type": "string", 
                    "enum": ["on", "off"] 
                },
                "duration": { 
                    "type": "number", 
                    "description": "Thời gian bơm tính bằng giây, mặc định là 60" 
                }
            },
            "required": ["state"]
        })",
        [](const String& args) {
            DynamicJsonDocument doc(256);
            deserializeJson(doc, args);
            
            String state = doc["state"].as<String>();
            int duration = doc.containsKey("duration") ? doc["duration"].as<int>() : 60;

            if (state == "on") {
                controlPump(true, duration);
            } else {
                controlPump(false, 0);
            }

            return WebSocketMCP::ToolResponse("{\"success\":true,\"state\":\"" + state + "\"}");
        }
    );
    Serial.println("[MCP] 🛠️ Đã đăng ký tool: pump_control");

    // 2. Tool điều khiển đèn LED
    mcpClient.registerTool(
        "led_control",
        "Điều khiển đèn chiếu sáng khu vườn",
        R"({
            "type": "object",
            "properties": {
                "state": { 
                    "type": "string", 
                    "enum": ["on", "off"] 
                }
            },
            "required": ["state"]
        })",
        [](const String& args) {
            DynamicJsonDocument doc(256);
            deserializeJson(doc, args);
            
            String state = doc["state"].as<String>();

            if (state == "on") {
                controlLed(true);
            } else {
                controlLed(false);
            }

            return WebSocketMCP::ToolResponse("{\"success\":true,\"state\":\"" + state + "\"}");
        }
    );
    Serial.println("[MCP] 🛠️ Đã đăng ký tool: led_control");

    /// 3. Tool đọc giá trị cảm biến (Đã cập nhật mô tả khắt khe hơn)
    mcpClient.registerTool(
        "get_sensor_data",
        "CHỈ kích hoạt để đọc giá trị cảm biến khi người dùng hỏi đích danh về 'trong nhà vườn' hoặc 'khu vườn'. BỎ QUA và không gọi tool này nếu người dùng hỏi thời tiết hoặc nhiệt độ chung chung.",
        R"({
            "type": "object",
            "properties": {}
        })",
        [](const String& args) {
            float t = readTemperature();
            float h = readHumidity();
            float s = readSoilMoisture();
            float thresh = getMoistureThreshold();

            // Tạo chuỗi JSON trả về cho Xiaozhi
            String response = "{\"temperature\":" + String(t) + 
                              ",\"air_humidity\":" + String(h) + 
                              ",\"soil_moisture\":" + String(s) + 
                              ",\"auto_pump_threshold\":" + String(thresh) + "}";
            
            Serial.println("[MCP] 📊 Xiaozhi vừa yêu cầu đọc cảm biến nhà vườn");
            return WebSocketMCP::ToolResponse(response);
        }
    );
    Serial.println("[MCP] 🛠️ Đã đăng ký tool: get_sensor_data");

    // 4. Tool thay đổi ngưỡng tưới tự động
    mcpClient.registerTool(
        "set_moisture_threshold",
        "Cài đặt ngưỡng độ ẩm đất để tự động bật máy bơm (tính bằng %)",
        R"({
            "type": "object",
            "properties": {
                "threshold": {
                    "type": "number",
                    "description": "Ngưỡng độ ẩm mới (%), ví dụ: 25, 30, 40"
                }
            },
            "required": ["threshold"]
        })",
        [](const String& args) {
            DynamicJsonDocument doc(256);
            deserializeJson(doc, args);
            
            if(doc.containsKey("threshold")) {
                float newThreshold = doc["threshold"].as<float>();
                setMoistureThreshold(newThreshold);
                return WebSocketMCP::ToolResponse("{\"success\":true,\"new_threshold\":" + String(newThreshold) + "}");
            }
            return WebSocketMCP::ToolResponse("{\"success\":false,\"error\":\"Thiếu thông số threshold\"}");
        }
    );
    Serial.println("[MCP] 🛠️ Đã đăng ký tool: set_moisture_threshold");
}

// Hàm khởi tạo MCP (Gọi trong setup)
void setupMCP() {
    Serial.println("[MCP] Đang khởi tạo kết nối...");
    mcpClient.begin(mcpEndpoint, onMcpConnectionStatus);
}

// Hàm duy trì MCP (Gọi trong loop)
void loopMCP() {
    mcpClient.loop();
}

#endif