#pragma once

// =============================================================================
//  EMBEDDED HTML — Sensor Node Provisioning Page
//  Wizard 2 bước: WiFi + Chọn Gateway → Đặt tên
//  Server URL và Provision Key đã cấu hình cứng trong firmware
// =============================================================================

const char PORTAL_HTML[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Cấu hình Sensor Node</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
      background: linear-gradient(135deg, #1a1a2e, #16213e, #0f3460);
      min-height: 100vh; color: #e0e0e0;
      display: flex; justify-content: center; align-items: center;
      padding: 16px;
    }
    .card {
      background: rgba(255,255,255,0.08);
      backdrop-filter: blur(20px);
      border: 1px solid rgba(255,255,255,0.15);
      border-radius: 20px; padding: 32px;
      width: 100%; max-width: 420px;
      box-shadow: 0 8px 32px rgba(0,0,0,0.3);
    }
    h1 {
      font-size: 1.4em; text-align: center; margin-bottom: 4px;
      background: linear-gradient(90deg, #00b894, #00cec9);
      -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    }
    .subtitle { text-align: center; font-size: 0.85em; color: #aaa; margin-bottom: 24px; }
    .step { display: none; }
    .step.active { display: block; }
    .step-indicator { display: flex; justify-content: center; gap: 8px; margin-bottom: 24px; }
    .step-dot {
      width: 10px; height: 10px; border-radius: 50%;
      background: rgba(255,255,255,0.2); transition: all 0.3s;
    }
    .step-dot.active { background: #00b894; transform: scale(1.3); }
    .step-dot.done { background: #4CAF50; }
    label { display: block; font-size: 0.85em; color: #bbb; margin-bottom: 6px; margin-top: 16px; }
    input, select {
      width: 100%; padding: 12px 14px; border: 1px solid rgba(255,255,255,0.2);
      border-radius: 10px; background: rgba(255,255,255,0.06);
      color: #fff; font-size: 1em; outline: none; transition: border 0.3s;
    }
    input:focus, select:focus { border-color: #00b894; }
    .btn {
      width: 100%; padding: 14px; border: none; border-radius: 12px;
      font-size: 1em; font-weight: 600; cursor: pointer;
      margin-top: 24px; transition: all 0.3s;
    }
    .btn-primary {
      background: linear-gradient(135deg, #00b894, #00cec9);
      color: #fff;
    }
    .btn-primary:hover { transform: translateY(-2px); box-shadow: 0 4px 15px rgba(0,184,148,0.3); }
    .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; transform: none; box-shadow: none; }
    .btn-secondary { background: rgba(255,255,255,0.1); color: #ccc; margin-top: 10px; }
    .wifi-list, .gw-list {
      max-height: 200px; overflow-y: auto; margin-top: 8px;
      border: 1px solid rgba(255,255,255,0.1); border-radius: 10px;
    }
    .wifi-item, .gw-item {
      padding: 10px 14px; cursor: pointer; display: flex;
      justify-content: space-between; align-items: center;
      border-bottom: 1px solid rgba(255,255,255,0.05);
      transition: background 0.2s;
    }
    .wifi-item:hover, .gw-item:hover { background: rgba(0,184,148,0.1); }
    .wifi-item.selected, .gw-item.selected {
      background: rgba(0,184,148,0.15); border-left: 3px solid #00b894;
    }
    .wifi-signal { font-size: 0.8em; color: #888; }
    .gw-status { font-size: 0.75em; padding: 2px 8px; border-radius: 10px; }
    .gw-status.online { background: rgba(76,175,80,0.2); color: #69f0ae; }
    .gw-status.offline { background: rgba(244,67,54,0.2); color: #ff6b6b; }
    .gw-location { font-size: 0.8em; color: #888; display: block; }
    .status {
      text-align: center; padding: 10px; border-radius: 8px;
      margin-top: 14px; font-size: 0.9em; display: none;
    }
    .status.error { display: block; background: rgba(244,67,54,0.2); color: #ff6b6b; }
    .status.success { display: block; background: rgba(76,175,80,0.2); color: #69f0ae; }
    .status.loading { display: block; background: rgba(0,184,148,0.1); color: #80deea; }
    .spinner {
      display: inline-block; width: 16px; height: 16px;
      border: 2px solid rgba(255,255,255,0.3); border-top-color: #00b894;
      border-radius: 50%; animation: spin 0.8s linear infinite;
      vertical-align: middle; margin-right: 8px;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .scan-btn {
      display: block; width: 100%; padding: 10px; margin-top: 10px;
      border: 1px dashed rgba(0,184,148,0.4); border-radius: 10px;
      background: transparent; color: #00b894; cursor: pointer;
      font-size: 0.9em; transition: all 0.3s;
    }
    .scan-btn:hover { background: rgba(0,184,148,0.1); }
    .scan-btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .info-box {
      background: rgba(0,184,148,0.08); border: 1px solid rgba(0,184,148,0.2);
      border-radius: 10px; padding: 12px; margin-top: 10px;
      font-size: 0.85em; color: #aaa;
    }
  </style>
</head>
<body>
  <div class="card">
    <h1>📡 Cấu hình Sensor Node</h1>
    <p class="subtitle">Hệ thống Giám sát Chất lượng Không khí</p>

    <div class="step-indicator">
      <div class="step-dot active" id="dot1"></div>
      <div class="step-dot" id="dot2"></div>
    </div>

    <!-- STEP 1: WiFi + Chọn Gateway -->
    <div class="step active" id="step1">
      <div class="info-box">
        ℹ️ WiFi chỉ dùng <b>tạm thời</b> để đăng ký với server. Sau khi cài đặt xong, WiFi sẽ tắt và node chỉ dùng LoRa.
      </div>

      <label>📡 Chọn mạng WiFi:</label>
      <div class="wifi-list" id="wifiList">
        <div style="padding:20px;text-align:center;color:#888;">Nhấn "Quét WiFi" để bắt đầu</div>
      </div>
      <button class="scan-btn" id="scanBtn" onclick="scanWifi()">🔍 Quét WiFi</button>

      <label>🔑 Mật khẩu WiFi:</label>
      <input type="password" id="wifiPass" placeholder="Nhập mật khẩu WiFi">

      <div class="status" id="status1"></div>
      <button class="btn btn-primary" id="nextBtn1" onclick="loadGateways()" disabled>Tải danh sách Gateway →</button>
    </div>

    <!-- STEP 2: Chọn Gateway + Tên + Lưu -->
    <div class="step" id="step2">
      <label>🏗️ Chọn Gateway gần nhất:</label>
      <div class="gw-list" id="gwList">
        <div style="padding:20px;text-align:center;color:#888;">Đang tải...</div>
      </div>

      <label>📝 Tên Sensor Node:</label>
      <input type="text" id="nodeName" placeholder="VD: Phòng họp 302">

      <label>📍 Vĩ độ (tuỳ chọn):</label>
      <input type="number" id="nodeLat" placeholder="VD: 10.7733" step="0.0001">

      <label>📍 Kinh độ (tuỳ chọn):</label>
      <input type="number" id="nodeLng" placeholder="VD: 106.6575" step="0.0001">

      <div class="status" id="status2"></div>
      <button class="btn btn-primary" id="saveBtn" onclick="saveConfig()">✅ Cài đặt</button>
      <button class="btn btn-secondary" onclick="goStep(1)">← Quay lại</button>
    </div>
  </div>

  <script>
    let selectedSSID = '';
    let selectedGW = '';

    function goStep(n) {
      document.querySelectorAll('.step').forEach(s => s.classList.remove('active'));
      document.getElementById('step' + n).classList.add('active');
      for (let i = 1; i <= 2; i++) {
        const dot = document.getElementById('dot' + i);
        dot.classList.remove('active', 'done');
        if (i < n) dot.classList.add('done');
        if (i === n) dot.classList.add('active');
      }
    }

    async function scanWifi() {
      const btn = document.getElementById('scanBtn');
      const list = document.getElementById('wifiList');
      btn.disabled = true;
      btn.textContent = '⏳ Đang quét...';
      list.innerHTML = '<div style="padding:20px;text-align:center;color:#888;"><span class="spinner"></span>Đang quét...</div>';
      try {
        const res = await fetch('/scan');
        const data = await res.json();
        list.innerHTML = '';
        if (data.networks && data.networks.length > 0) {
          data.networks.forEach(net => {
            const div = document.createElement('div');
            div.className = 'wifi-item';
            div.innerHTML = `<span>${net.ssid}</span><span class="wifi-signal">${net.rssi} dBm ${net.secure ? '🔒' : ''}</span>`;
            div.onclick = () => selectWifi(net.ssid, div);
            list.appendChild(div);
          });
        } else {
          list.innerHTML = '<div style="padding:20px;text-align:center;color:#888;">Không tìm thấy mạng WiFi</div>';
        }
      } catch(e) {
        list.innerHTML = '<div style="padding:20px;text-align:center;color:#ff6b6b;">Lỗi quét WiFi</div>';
      }
      btn.disabled = false;
      btn.textContent = '🔍 Quét lại';
    }

    function selectWifi(ssid, el) {
      document.querySelectorAll('.wifi-item').forEach(i => i.classList.remove('selected'));
      el.classList.add('selected');
      selectedSSID = ssid;
      document.getElementById('nextBtn1').disabled = false;
    }

    async function loadGateways() {
      const status = document.getElementById('status1');
      const wifiPass = document.getElementById('wifiPass').value;

      if (!selectedSSID) { showStatus(status, 'error', 'Vui lòng chọn mạng WiFi'); return; }

      showStatus(status, 'loading', '<span class="spinner"></span>Đang kết nối WiFi và tải danh sách gateway...');
      document.getElementById('nextBtn1').disabled = true;

      try {
        const res = await fetch('/gateways', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            wifi_ssid: selectedSSID,
            wifi_pass: wifiPass
          })
        });
        const data = await res.json();
        if (data.success && data.gateways) {
          showStatus(status, 'success', '✅ Đã kết nối server!');
          renderGateways(data.gateways);
          setTimeout(() => goStep(2), 500);
        } else {
          showStatus(status, 'error', '❌ ' + (data.error || 'Lỗi tải danh sách gateway'));
          document.getElementById('nextBtn1').disabled = false;
        }
      } catch(e) {
        showStatus(status, 'error', '❌ Không thể kết nối');
        document.getElementById('nextBtn1').disabled = false;
      }
    }

    function renderGateways(gateways) {
      const list = document.getElementById('gwList');
      list.innerHTML = '';
      if (gateways.length === 0) {
        list.innerHTML = '<div style="padding:20px;text-align:center;color:#888;">Chưa có gateway nào</div>';
        return;
      }
      gateways.forEach(gw => {
        const div = document.createElement('div');
        div.className = 'gw-item';
        div.innerHTML = `
          <div>
            <strong>${gw.name}</strong>
            <span class="gw-location">${gw.location_desc || ''}</span>
          </div>
          <span class="gw-status ${gw.status}">${gw.status === 'online' ? '🟢 Online' : '🔴 Offline'}</span>
        `;
        div.onclick = () => selectGW(gw.id, div);
        list.appendChild(div);
      });
    }

    function selectGW(id, el) {
      document.querySelectorAll('.gw-item').forEach(i => i.classList.remove('selected'));
      el.classList.add('selected');
      selectedGW = id;
    }

    async function saveConfig() {
      const btn = document.getElementById('saveBtn');
      const status = document.getElementById('status2');
      const nodeName = document.getElementById('nodeName').value.trim();
      const lat = document.getElementById('nodeLat').value;
      const lng = document.getElementById('nodeLng').value;

      if (!nodeName) { showStatus(status, 'error', 'Vui lòng nhập tên node'); return; }
      if (!selectedGW) { showStatus(status, 'error', 'Vui lòng chọn gateway'); return; }

      btn.disabled = true;
      showStatus(status, 'loading', '<span class="spinner"></span>Đang cài đặt...');

      try {
        const body = { name: nodeName, gateway_id: selectedGW };
        if (lat && lng) { body.lat = parseFloat(lat); body.lng = parseFloat(lng); }

        const res = await fetch('/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body)
        });
        const data = await res.json();
        if (data.success) {
          showStatus(status, 'success',
            '✅ Cài đặt thành công!<br>Node ID: ' + data.node_id +
            '<br>Đang khởi động lại...');
        } else {
          showStatus(status, 'error', '❌ ' + (data.error || 'Lỗi'));
          btn.disabled = false;
        }
      } catch(e) {
        showStatus(status, 'error', '❌ Không thể kết nối');
        btn.disabled = false;
      }
    }

    function showStatus(el, type, msg) {
      el.className = 'status ' + type;
      el.innerHTML = msg;
    }
  </script>
</body>
</html>
)rawliteral";
