import { Angry, Annoyed, Clock, Droplets, Frown, type LucideIcon, Meh, Skull, Smile, Thermometer } from "lucide-react";
import type { Reading, Units } from "@/api/types";
import { aqiLevel } from "@/lib/aqi";
import { EMPTY, formatNumber, formatTime } from "@/lib/format";

// Biểu tượng khuôn mặt theo mức AQI (giống IQAir); đi kèm nhãn chữ nên không chỉ dựa vào hình
const FACES: Record<string, LucideIcon> = {
  good: Smile,
  moderate: Meh,
  usg: Annoyed,
  unhealthy: Frown,
  very_unhealthy: Angry,
  hazardous: Skull,
};

/**
 * Thẻ AQI gọn kiểu IQAir: khối màu theo mức (số AQI do backend tính), dòng PM2.5 và dải nhiệt độ, độ ẩm,
 * giờ đo của số đo mới nhất. Không có AQI thì thẻ xám.
 */
export function AqiCard({ latest, units, stale }: { latest: Reading | null; units: Units; stale: boolean }) {
  const aqi = latest?.aqi_instant ?? null;
  const level = aqiLevel(aqi);
  const Face = level ? FACES[level.key] : Meh;
  const style = level ? { background: level.color, color: level.text } : undefined;

  return (
    <section className={`aqi-card ${level ? "" : "aqi-card--empty"}`} aria-label="Chỉ số chất lượng không khí">
      <div className="aqi-card__head" style={style}>
        <div className="aqi-card__box">
          <strong>{aqi ?? EMPTY}</strong>
          <span>AQI Mỹ</span>
        </div>
        <div className="aqi-card__level">
          <p>{level ? level.label : "Chưa có AQI"}</p>
          <small>
            AQI tức thời
            {stale && <span className="aqi-card__stale">Số đo cũ</span>}
          </small>
        </div>
        <Face className="aqi-card__face" size={40} strokeWidth={1.5} aria-hidden="true" />
      </div>

      <p className="aqi-card__row" style={style}>
        <span>
          Bụi mịn <strong>PM2.5</strong>
        </span>
        <span>
          {formatNumber(latest?.pm25)} {latest?.pm25 != null && units.pm25}
        </span>
      </p>

      <dl className="aqi-card__weather">
        <div>
          <dt>
            <Thermometer size={16} aria-hidden="true" />
            <span className="sr-only">Nhiệt độ</span>
          </dt>
          <dd>
            {formatNumber(latest?.temperature)}
            {latest?.temperature != null && units.temperature}
          </dd>
        </div>
        <div>
          <dt>
            <Droplets size={16} aria-hidden="true" />
            <span className="sr-only">Độ ẩm</span>
          </dt>
          <dd>
            {formatNumber(latest?.humidity, 0)}
            {latest?.humidity != null && ` ${units.humidity}`}
          </dd>
        </div>
        <div>
          <dt>
            <Clock size={16} aria-hidden="true" />
            <span className="sr-only">Đo lúc</span>
          </dt>
          <dd>{latest ? formatTime(Date.parse(latest.measured_at)) : EMPTY}</dd>
        </div>
      </dl>
    </section>
  );
}
