import type { Reading, Units } from "@/api/types";
import { aqiLevel } from "@/lib/aqi";
import { EMPTY, formatDateTime, formatNumber } from "@/lib/format";

/** Thẻ AQI nổi bật kiểu IQAir: khối màu theo mức AQI (số do backend tính) + PM2.5, PM10 của số đo mới nhất. */
export function AqiHero({ latest, units, stale }: { latest: Reading | null; units: Units; stale: boolean }) {
  const aqi = latest?.aqi_instant ?? null;
  const level = aqiLevel(aqi);
  const style = level ? { background: level.color, color: level.text } : undefined;

  return (
    <section className="aqi-hero" aria-label="Chỉ số chất lượng không khí">
      <div className={`aqi-hero__score ${level ? "" : "aqi-hero__score--empty"}`} style={style}>
        <span className="aqi-hero__caption">
          AQI Mỹ tức thời
          {stale && <span className="aqi-hero__stale">Số đo cũ</span>}
        </span>
        <strong className="aqi-hero__value">{aqi ?? EMPTY}</strong>
        <span className="aqi-hero__level">{level ? level.label : "Chưa có AQI"}</span>
      </div>

      <div className="aqi-hero__body" style={level ? { background: level.soft } : undefined}>
        <dl className="aqi-hero__stats">
          <div>
            <dt>PM2.5</dt>
            <dd>
              {formatNumber(latest?.pm25)} {latest?.pm25 != null && <small>{units.pm25}</small>}
            </dd>
          </div>
          <div>
            <dt>PM10</dt>
            <dd>
              {formatNumber(latest?.pm10)} {latest?.pm10 != null && <small>{units.pm10}</small>}
            </dd>
          </div>
        </dl>
        <p className="aqi-hero__note">
          {latest ? (
            <>
              Đo lúc <strong>{formatDateTime(latest.measured_at)}</strong>
              {stale && " · số đo cũ"}. AQI do backend tính từ PM2.5 và PM10.
            </>
          ) : (
            "Node chưa có số đo nào."
          )}
        </p>
      </div>
    </section>
  );
}
