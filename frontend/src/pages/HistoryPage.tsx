import { RadioTower, RefreshCw, ServerCrash } from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { fetchNodes, fetchReadings } from "@/api/dev";
import type { NodeInfo, NodeReadings, RangeHours } from "@/api/types";
import { type ChartSeries, SeriesChart } from "@/components/charts/SeriesChart";
import { EmptyState } from "@/components/common/EmptyState";
import { StatusBanner } from "@/components/common/StatusBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { RefreshControl } from "@/components/layout/RefreshControl";
import { usePolling } from "@/hooks/usePolling";
import { aqiLevel } from "@/lib/aqi";
import { EMPTY, formatClock, formatNumber } from "@/lib/format";

const POLL_MS = 30_000; // lịch sử đổi chậm: làm mới mỗi 30 giây
const RANGES: { hours: RangeHours; label: string }[] = [
  { hours: 1, label: "1 giờ" },
  { hours: 6, label: "6 giờ" },
  { hours: 24, label: "24 giờ" },
  { hours: 168, label: "7 ngày" },
  { hours: 720, label: "30 ngày" },
];
const DEFAULT_RANGE: RangeHours = 24;

type MetricKey = "aqi" | "pm25" | "pm10" | "temperature" | "humidity";

interface Metric {
  key: MetricKey;
  label: string;
  unit: (r: NodeReadings) => string;
  color: string;
  digits: number;
}

// Các chỉ số trên trang; màu khác nhau và có nét đứt cho chuỗi thứ hai của cùng biểu đồ
const METRICS: Metric[] = [
  { key: "aqi", label: "AQI Mỹ", unit: () => "", color: "#64748B", digits: 0 },
  { key: "pm25", label: "PM2.5", unit: (r) => r.units.pm25, color: "#1D4ED8", digits: 1 },
  { key: "pm10", label: "PM10", unit: (r) => r.units.pm10, color: "#0E7490", digits: 1 },
  { key: "temperature", label: "Nhiệt độ", unit: (r) => r.units.temperature, color: "#DC2626", digits: 1 },
  { key: "humidity", label: "Độ ẩm", unit: (r) => r.units.humidity, color: "#0369A1", digits: 1 },
];

interface HistoryData {
  nodes: NodeInfo[];
  detail: NodeReadings | null;
}

/** Chuỗi [thời điểm ms, giá trị] của một chỉ số: số đo thô (AQI tức thời) hoặc trung bình giờ (AQI giờ tính từ PM). */
function points(detail: NodeReadings, key: MetricKey): [number, number | null][] {
  if (detail.resolution === "hour") {
    return detail.hourly.map((h) => [Date.parse(h.time), h[key]]);
  }
  return detail.readings.map((r) => [Date.parse(r.measured_at), key === "aqi" ? r.aqi_instant : r[key]]);
}

/** Trung bình, thấp nhất, cao nhất và số giá trị của một chuỗi (bỏ null); không có giá trị thì null. */
function stats(values: (number | null)[]): { avg: number; min: number; max: number; n: number } | null {
  const v = values.filter((x): x is number => x !== null);
  if (v.length === 0) return null;
  return { avg: v.reduce((a, b) => a + b, 0) / v.length, min: Math.min(...v), max: Math.max(...v), n: v.length };
}

/**
 * Trang Lịch sử: chọn trạm, khoảng thời gian (1 giờ → 30 ngày) và các chỉ số cần xem; thẻ thống kê
 * trung bình/thấp nhất/cao nhất; biểu đồ AQI, bụi mịn (so sánh PM2.5 với PM10), nhiệt độ – độ ẩm,
 * có tooltip, hiệu ứng và kéo chọn đoạn thời gian. Trạm và khoảng nằm trên URL (?node=&range=).
 */
export function HistoryPage() {
  const [params, setParams] = useSearchParams();
  const selectedId = Number(params.get("node")) || null;
  const rangeParam = Number(params.get("range")) as RangeHours;
  const hours = RANGES.some((r) => r.hours === rangeParam) ? rangeParam : DEFAULT_RANGE;
  const [hidden, setHidden] = useState<Set<MetricKey>>(new Set());

  // Đổi một tham số trên URL, giữ các tham số còn lại
  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    next.set(key, value);
    setParams(next, { replace: true });
  };

  const load = useCallback(
    async (signal: AbortSignal): Promise<HistoryData> => {
      const nodes = await fetchNodes(signal);
      const node = nodes.find((n) => n.id === selectedId) ?? nodes[0];
      return { nodes, detail: node ? await fetchReadings(node.id, hours, signal) : null };
    },
    [selectedId, hours],
  );
  const { data, error, loading, lastSuccessAt, refresh } = usePolling(load, `${selectedId}-${hours}`, POLL_MS);
  const detail = data?.detail ?? null;

  // Chuỗi số liệu của từng chỉ số, tính lại khi có dữ liệu mới
  const series = useMemo(() => {
    if (!detail) return null;
    return Object.fromEntries(METRICS.map((m) => [m.key, points(detail, m.key)])) as Record<MetricKey, [number, number | null][]>;
  }, [detail]);

  const toggle = (key: MetricKey) =>
    setHidden((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const rangeLabel = RANGES.find((r) => r.hours === hours)!.label;
  const header = (
    <PageHeader
      eyebrow="Lịch sử"
      title="Lịch sử chất lượng không khí"
      subtitle={detail ? `Trạm ${detail.node.name} (${detail.node.station_code}) · ${rangeLabel} gần nhất` : "Dữ liệu đã lưu của các trạm"}
      actions={<RefreshControl lastSuccessAt={lastSuccessAt} loading={loading} onRefresh={refresh} intervalS={POLL_MS / 1000} />}
    />
  );

  if (!data) {
    return (
      <>
        {header}
        {error ? (
          <EmptyState
            icon={ServerCrash}
            title="Mất kết nối tới máy chủ"
            action={
              <button type="button" className="btn btn--primary" onClick={refresh}>
                <RefreshCw size={16} aria-hidden="true" /> Thử lại
              </button>
            }
          >
            {error.message}. Tự thử lại sau 30 giây.
          </EmptyState>
        ) : (
          <div className="skeleton skeleton--chart" aria-busy="true" aria-label="Đang tải dữ liệu" />
        )}
      </>
    );
  }

  if (!detail || !series) {
    return (
      <>
        {header}
        <EmptyState icon={RadioTower} title="Chưa có trạm nào">
          Lịch sử xuất hiện khi Gateway gửi số đo đầu tiên của node.
        </EmptyState>
      </>
    );
  }

  const hourly = detail.resolution === "hour";
  const visible = METRICS.filter((m) => !hidden.has(m.key));
  const chartSeries = (keys: MetricKey[], axisOf: (k: MetricKey) => 0 | 1 = () => 0): ChartSeries[] =>
    visible
      .filter((m) => keys.includes(m.key))
      .map((m, i) => ({
        name: m.label,
        unit: m.unit(detail),
        color: m.color,
        dashed: i > 0,
        axis: axisOf(m.key),
        digits: m.digits,
        points: series[m.key],
        bar: m.key === "aqi" && hourly,
        colorOf: m.key === "aqi" ? (v: number) => aqiLevel(v)?.color : undefined,
      }));
  const charts = [
    { id: "aqi", title: hourly ? "AQI Mỹ theo giờ" : "AQI Mỹ tức thời", series: chartSeries(["aqi"]) },
    { id: "pm", title: "Bụi mịn: so sánh PM2.5 và PM10", series: chartSeries(["pm25", "pm10"]) },
    {
      id: "climate",
      title: "Nhiệt độ và độ ẩm",
      series: chartSeries(["temperature", "humidity"], (k) => (k === "humidity" ? 1 : 0)),
    },
  ].filter((c) => c.series.length > 0);
  const nSource = hourly ? detail.hourly.filter((h) => h.n_samples > 0).length : detail.readings.length;

  return (
    <main className="overview">
      {header}

      {error && (
        <StatusBanner tone="offline" title="Mất kết nối tới máy chủ">
          Đang hiển thị dữ liệu tải lúc {lastSuccessAt ? formatClock(lastSuccessAt) : EMPTY}. Tự thử lại sau 30 giây.
        </StatusBanner>
      )}

      <section className="card filters" aria-label="Bộ lọc">
        {data.nodes.length > 0 && (
          <label className="field">
            <span>Trạm</span>
            <select value={detail.node.id} onChange={(e) => update("node", e.target.value)}>
              {data.nodes.map((n) => (
                <option key={n.id} value={n.id}>
                  {n.name} · {n.station_code}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="field">
          <span id="range-label">Khoảng thời gian</span>
          <div className="segmented" role="group" aria-labelledby="range-label">
            {RANGES.map((r) => (
              <button key={r.hours} type="button" aria-pressed={hours === r.hours} onClick={() => update("range", String(r.hours))}>
                {r.label}
              </button>
            ))}
          </div>
        </div>
        <div className="field">
          <span id="metrics-label">Chỉ số</span>
          <div className="chips" role="group" aria-labelledby="metrics-label">
            {METRICS.map((m) => (
              <button key={m.key} type="button" className="chip" aria-pressed={!hidden.has(m.key)} onClick={() => toggle(m.key)}>
                <span className="chip__dot" style={{ background: m.color }} aria-hidden="true" />
                {m.label}
              </button>
            ))}
          </div>
        </div>
      </section>

      <p className="section__sub">
        {hourly
          ? `Mỗi điểm là trung bình một giờ (nhãn là giờ kết thúc), bỏ số đo cách ly; ${nSource} giờ có dữ liệu. AQI giờ do backend tính từ PM trung bình.`
          : `Số đo thô: ${nSource.toLocaleString("vi-VN")} số đo${detail.truncated ? " (đã giới hạn số điểm)" : ""}. AQI tức thời do backend tính.`}
      </p>

      {visible.length > 0 && (
        <div className="stats" aria-label="Thống kê trong khoảng đã chọn">
          {visible.map((m) => {
            const st = stats(series[m.key].map(([, v]) => v));
            const unit = m.unit(detail);
            const level = m.key === "aqi" && st ? aqiLevel(Math.round(st.avg)) : null;
            return (
              <article key={m.key} className="stat">
                <h3 className="stat__label">
                  <span className="chip__dot" style={{ background: level?.color ?? m.color }} aria-hidden="true" />
                  {m.label} trung bình
                </h3>
                <p className="stat__value">
                  {st ? formatNumber(st.avg, m.digits) : EMPTY}
                  {st && unit && <small> {unit}</small>}
                </p>
                <p className="stat__range">
                  {st ? `Thấp nhất ${formatNumber(st.min, m.digits)} · Cao nhất ${formatNumber(st.max, m.digits)}` : "Không có dữ liệu"}
                </p>
              </article>
            );
          })}
        </div>
      )}

      {charts.map((c) => (
        <article key={c.id} className="panel">
          <h2 className="panel__title">{c.title}</h2>
          <SeriesChart title={c.title} series={c.series} zoom emptyText={`Chưa có dữ liệu trong ${rangeLabel} gần nhất`} />
        </article>
      ))}
      {charts.length === 0 && (
        <EmptyState icon={RadioTower} title="Chưa chọn chỉ số nào">
          Bật ít nhất một chỉ số ở bộ lọc phía trên để xem biểu đồ.
        </EmptyState>
      )}
    </main>
  );
}
