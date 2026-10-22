// Định dạng số và thời gian theo quy ước frontend_design 7: giờ Việt Nam, null hiển thị "—".

export const EMPTY = "—";
const TIME_ZONE = "Asia/Ho_Chi_Minh";

const dateTimeFmt = new Intl.DateTimeFormat("vi-VN", {
  timeZone: TIME_ZONE,
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});
const timeFmt = new Intl.DateTimeFormat("vi-VN", { timeZone: TIME_ZONE, hour: "2-digit", minute: "2-digit" });
const clockFmt = new Intl.DateTimeFormat("vi-VN", {
  timeZone: TIME_ZONE,
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

/** Số có `digits` chữ số thập phân; null/undefined → "—" (không đổi thành 0). */
export function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EMPTY;
  return value.toLocaleString("vi-VN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

/** "15/10 14:05:30" theo giờ Việt Nam; null → "—". */
export function formatDateTime(iso: string | Date | null | undefined): string {
  if (!iso) return EMPTY;
  const parts = Object.fromEntries(
    dateTimeFmt.formatToParts(typeof iso === "string" ? new Date(iso) : iso).map((p) => [p.type, p.value]),
  );
  return `${parts.day}/${parts.month} ${parts.hour}:${parts.minute}:${parts.second}`;
}

/** "14:05" theo giờ Việt Nam (nhãn trục thời gian). */
export function formatTime(ms: number): string {
  return timeFmt.format(new Date(ms));
}

/** "14:05:30" theo giờ Việt Nam. */
export function formatClock(date: Date): string {
  return clockFmt.format(date);
}

/** Khoảng thời gian đã trôi qua: "12 giây trước", "5 phút trước", "2 giờ trước". */
export function formatAge(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return EMPTY;
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))} giây trước`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} phút trước`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} giờ trước`;
  return `${Math.floor(seconds / 86400)} ngày trước`;
}

/** Số giây → "65 phút" / "2 giờ" (mô tả ngưỡng). */
export function formatDuration(seconds: number): string {
  return seconds < 3600 ? `${Math.round(seconds / 60)} phút` : `${formatNumber(seconds / 3600, 1)} giờ`;
}
