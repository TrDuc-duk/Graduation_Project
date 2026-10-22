// Thang AQI Mỹ (US EPA): 6 mức theo ngưỡng chuẩn, nhãn tiếng Việt và màu theo phong cách IQAir.
// Màu chữ `text` đạt tương phản ≥ 4,5:1 trên nền `color` (WCAG AA).
// Chỉ dùng để TÔ MÀU số AQI do backend trả về; frontend không tự tính AQI (frontend_design 1).
// Tạm đặt ở frontend cho tới khi có API /public/aqi-scale.

export interface AqiLevel {
  key: string;
  label: string; // nhãn tiếng Việt
  min: number;
  max: number;
  color: string; // màu nền của mức (đậm, dùng cho chấm/thanh)
  soft: string; // nền nhạt cho thẻ lớn
  text: string; // màu chữ đặt trên nền mức, đủ tương phản
}

export const AQI_LEVELS: AqiLevel[] = [
  { key: "good", label: "Tốt", min: 0, max: 50, color: "#a8e05f", soft: "#eef8e0", text: "#3f5a1a" },
  { key: "moderate", label: "Trung bình", min: 51, max: 100, color: "#fdd64b", soft: "#fff7d6", text: "#6b5310" },
  {
    key: "usg",
    label: "Không tốt cho nhóm nhạy cảm",
    min: 101,
    max: 150,
    color: "#ff9b57",
    soft: "#ffeedf",
    text: "#5e2606",
  },
  { key: "unhealthy", label: "Không lành mạnh", min: 151, max: 200, color: "#fe6a69", soft: "#ffe4e3", text: "#4e0d10" },
  { key: "very_unhealthy", label: "Rất không tốt", min: 201, max: 300, color: "#a97abc", soft: "#f2e9f6", text: "#2a1033" },
  { key: "hazardous", label: "Nguy hiểm", min: 301, max: 500, color: "#a87383", soft: "#f3e6ea", text: "#26080f" },
];

/** Mức AQI chứa giá trị `aqi` (trên 500 xếp vào "Nguy hiểm"); null khi không có AQI. */
export function aqiLevel(aqi: number | null | undefined): AqiLevel | null {
  if (aqi === null || aqi === undefined || Number.isNaN(aqi)) return null;
  return AQI_LEVELS.find((l) => aqi <= l.max) ?? AQI_LEVELS[AQI_LEVELS.length - 1];
}
