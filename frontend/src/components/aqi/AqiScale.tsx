import { AQI_LEVELS, type AqiLevel } from "@/lib/aqi";

/**
 * Chú giải 6 mức AQI Mỹ; mức hiện tại được đánh dấu bằng viền và chữ "Hiện tại" (không chỉ dựa vào màu).
 * `vertical`: xếp dọc trong một thẻ (trang Tổng quan); mặc định xếp ngang.
 */
export function AqiScale({ current, vertical }: { current?: AqiLevel | null; vertical?: boolean }) {
  return (
    <ol className={`aqi-scale ${vertical ? "aqi-scale--vertical" : ""}`} aria-label="Thang AQI Mỹ">
      {AQI_LEVELS.map((level) => {
        const active = current?.key === level.key;
        return (
          <li
            key={level.key}
            className={`aqi-scale__item ${active ? "aqi-scale__item--active" : ""}`}
            style={{ background: level.color, color: level.text }}
            aria-current={active ? "true" : undefined}
          >
            <span className="aqi-scale__label">{level.label}</span>
            <span className="aqi-scale__range">
              {level.min}–{level.max}
              {active && <strong> · Hiện tại</strong>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
