// Kiểu dữ liệu khớp schema của backend: backend/app/modules/dev/schemas.py

export interface GatewayInfo {
  id: string;
  name: string;
  status: string;
  online: boolean;
  last_seen_at: string | null;
  last_telemetry_at: string | null;
}

export interface Freshness {
  last_received_at: string | null;
  age_s: number | null;
  stale_after_s: number;
  is_stale: boolean;
}

export interface NodeInfo {
  id: number;
  station_code: string;
  device_code: string;
  name: string;
  district: string | null;
  latitude: number | null; // null khi chưa nhập vị trí
  longitude: number | null;
  status: string;
  connectivity: string;
  battery_pct: number | null;
  effective_interval_s: number | null;
  last_seen_at: string | null;
  last_measurement_at: string | null;
  gateway: GatewayInfo | null;
  freshness: Freshness;
  latest: Reading | null; // số đo mới nhất
}

/** Một số đo thô. null = cảm biến lỗi/thiếu, KHÔNG phải 0. */
export interface Reading {
  measured_at: string;
  received_at: string;
  gateway_id: string;
  time_source: string;
  pm25: number | null;
  pm10: number | null;
  co2: number | null;
  tvoc: number | null;
  temperature: number | null;
  humidity: number | null;
  battery_pct: number | null;
  aqi_instant: number | null;
  qc_flags: number;
  quarantined: boolean;
  time_unreliable: boolean;
}

// 1, 6, 24 giờ: số đo thô; 168, 720 giờ (7, 30 ngày): trung bình theo giờ
export type RangeHours = 1 | 6 | 24 | 168 | 720;

export type Units = Record<"pm25" | "pm10" | "co2" | "tvoc" | "temperature" | "humidity" | "battery", string>;

/** Trung bình một giờ; nhãn `time` là giờ kết thúc của cửa sổ (time − 1 giờ, time]. Giờ trống: giá trị null. */
export interface HourlyPoint {
  time: string;
  n_samples: number;
  pm25: number | null;
  pm10: number | null;
  co2: number | null;
  tvoc: number | null;
  temperature: number | null;
  humidity: number | null;
  aqi: number | null; // backend tính từ PM trung bình giờ
}

export interface NodeReadings {
  node: NodeInfo;
  hours: RangeHours;
  resolution: "raw" | "hour";
  since: string;
  server_time: string;
  units: Units;
  latest: Reading | null;
  readings: Reading[];
  hourly: HourlyPoint[];
  truncated: boolean;
}
