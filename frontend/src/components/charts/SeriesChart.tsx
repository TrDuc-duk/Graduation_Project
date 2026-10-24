import { LineChart } from "echarts/charts";
import { AriaComponent, DataZoomComponent, GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";
import { EMPTY, formatDateTime, formatDayHour, formatNumber, formatTime } from "@/lib/format";

// Chỉ nạp các phần ECharts thực sự dùng (frontend_design 2)
echarts.use([LineChart, GridComponent, TooltipComponent, LegendComponent, AriaComponent, DataZoomComponent, CanvasRenderer]);

export interface ChartSeries {
  name: string;
  unit: string;
  color: string;
  axis: 0 | 1; // 0: trục trái, 1: trục phải (đại lượng khác đơn vị)
  digits: number;
  points: [number, number | null][]; // [thời điểm ms, giá trị]; null tạo khoảng đứt
  colorOf?: (value: number) => string | undefined; // màu điểm dữ liệu theo giá trị (vd. mức AQI)
}

interface Props {
  title: string;
  series: ChartSeries[];
  emptyText: string;
  zoom?: boolean; // thanh kéo chọn đoạn thời gian (dataZoom) dưới biểu đồ, cuộn/kéo trong biểu đồ để phóng to
}

const LONG_SPAN_MS = 36 * 3600 * 1000; // khoảng dài hơn 36 giờ: nhãn trục ghi cả ngày

const AXIS_TEXT = "#475569";
const GRID_LINE = "#EDF1F6";
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Biểu đồ đường theo thời gian; mỗi trục y ghi rõ đơn vị, giá trị null để đứt quãng (không nội suy). */
export function SeriesChart({ title, series, emptyText, zoom }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);
  const hasData = series.some((s) => s.points.some(([, v]) => v !== null));

  // Tạo chart một lần, tự co giãn theo khung
  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current, undefined, { renderer: "canvas" });
    chartRef.current = chart;
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(ref.current);
    return () => {
      observer.disconnect();
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  // Cập nhật dữ liệu mỗi lần polling
  useEffect(() => {
    chartRef.current?.setOption(buildOption(title, series, zoom), { notMerge: true });
  }, [title, series, zoom]);

  return (
    <div className={`chart ${zoom ? "chart--zoom" : ""}`}>
      <div ref={ref} className="chart__canvas" role="img" aria-label={`${title}: ${series.map((s) => withUnit(s.name, s.unit)).join(", ")}`} />
      {!hasData && <p className="chart__empty">{emptyText}</p>}
      {hasData && (
        <div className="chart__summary" aria-label="Giá trị gần nhất của từng chỉ số">
          {series.map((s) => {
            const latest = s.points.at(-1);
            return (
              <div key={s.name} className="chart__reading">
                <span className="chart__dot" style={{ backgroundColor: s.color }} aria-hidden="true" />
                <span>{s.name}</span>
                <strong>{formatNumber(latest?.[1] ?? null, s.digits)} <small>{s.unit}</small></strong>
              </div>
            );
          })}
          <span className="chart__note">Mẫu cuối · Khoảng thiếu dữ liệu được để trống</span>
        </div>
      )}
    </div>
  );
}

/** "PM2.5 (µg/m³)"; đại lượng không có đơn vị (AQI) thì chỉ tên. */
function withUnit(name: string, unit: string): string {
  return unit ? `${name} (${unit})` : name;
}

/** Cấu hình ECharts: một hoặc hai trục y (trái/phải), mỗi trục mang đơn vị của đại lượng trên nó. */
function buildOption(title: string, series: ChartSeries[], zoom?: boolean): echarts.EChartsCoreOption {
  const axes = [0, 1].filter((a) => series.some((s) => s.axis === a));
  const times = series.flatMap((s) => s.points.map(([t]) => t));
  const long = times.length > 0 && Math.max(...times) - Math.min(...times) > LONG_SPAN_MS;
  return {
    animation: !reducedMotion,
    animationDuration: 450,
    animationDurationUpdate: reducedMotion ? 0 : 250,
    textStyle: { fontFamily: '"Be Vietnam Pro", sans-serif' },
    aria: { enabled: true, label: { description: title } },
    grid: { left: 4, right: 12, top: 66, bottom: zoom ? 62 : 12, containLabel: true },
    dataZoom: zoom
      ? [
          { type: "inside", filterMode: "none" },
          { type: "slider", height: 24, bottom: 8, borderColor: "transparent", backgroundColor: "#F1F5F9", fillerColor: "rgba(37, 99, 235, 0.12)", handleStyle: { color: "#2563EB", borderColor: "#FFFFFF" }, moveHandleSize: 0, filterMode: "none", labelFormatter: (v: number) => (Number.isFinite(v) ? formatDayHour(v) : "") },
        ]
      : undefined,
    legend: { type: "scroll", top: 4, left: 0, right: 0, itemWidth: 22, itemHeight: 8, itemGap: 24, textStyle: { color: AXIS_TEXT, fontSize: 12 }, data: series.map((s, i) => ({ name: s.name, icon: i % 2 ? "diamond" : "circle" })) },
    tooltip: {
      trigger: "axis",
      confine: true,
      backgroundColor: "rgba(255, 255, 255, 0.98)",
      borderColor: "#E2E8F0",
      borderWidth: 1,
      padding: [12, 14],
      extraCssText: "border-radius:12px;box-shadow:0 8px 28px rgba(15,23,42,.12);max-width:calc(100% - 16px);white-space:normal;",
      textStyle: { color: "#0F172A", fontSize: 12 },
      axisPointer: { type: "line", lineStyle: { color: "#94A3B8", type: "dashed" } },
      formatter: (params: unknown) => tooltipHtml(params as TooltipParam[], series),
    },
    xAxis: {
      type: "time",
      splitNumber: 4,
      axisTick: { show: false },
      axisLabel: { margin: 12, fontSize: 11, color: AXIS_TEXT, formatter: (v: number) => (long ? formatDayHour(v) : formatTime(v)), hideOverlap: true },
      axisLine: { lineStyle: { color: GRID_LINE } },
      splitLine: { show: false },
    },
    yAxis: axes.map((a) => {
      const onAxis = series.filter((s) => s.axis === a);
      return {
        type: "value",
        position: a === 0 ? "left" : "right",
        name: onAxis[0].unit || onAxis.map((s) => s.name).join(" / "),
        nameGap: 18,
        splitNumber: 4,
        nameTextStyle: { color: onAxis.length === 1 ? onAxis[0].color : AXIS_TEXT, fontWeight: 600, align: a === 0 ? "left" : "right" },
        scale: true,
        axisLabel: { color: AXIS_TEXT, fontSize: 11, margin: 10 },
        splitLine: { show: a === 0, lineStyle: { color: GRID_LINE } },
      };
    }),
    series: series.map((s, index) => ({
      name: s.name,
      type: "line",
      yAxisIndex: axes.indexOf(s.axis),
      data: s.points,
      color: s.color,
      connectNulls: false,
      showSymbol: s.points.filter(([, v]) => v !== null).length < 2,
      symbol: index % 2 ? "diamond" : "circle",
      symbolSize: 7,
      smooth: false,
      lineStyle: { width: 2.5, type: "solid", color: s.color, cap: "round", join: "round" },
      areaStyle: index === 0 ? {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: s.color },
          { offset: 1, color: "rgba(255,255,255,0)" },
        ]),
        opacity: 0.12,
      } : undefined,
      emphasis: { focus: "series", lineStyle: { width: 3.5 }, scale: 1.4 },
      itemStyle: {
        color: s.colorOf
          ? (p: { value: [number, number | null] }) => (p.value[1] === null ? s.color : (s.colorOf!(p.value[1]) ?? s.color))
          : s.color,
        borderColor: "#FFFFFF",
        borderWidth: 2,
      },
    })),
  };
}

interface TooltipParam {
  seriesIndex: number;
  value: [number, number | null];
  marker: string;
}

/** Nội dung tooltip: thời điểm đo và từng giá trị kèm đơn vị; null hiển thị "—". */
function tooltipHtml(params: TooltipParam[], series: ChartSeries[]): string {
  if (!params.length) return "";
  const time = formatDateTime(new Date(params[0].value[0]));
  // Gateway có thể gửi nhiều mẫu cùng timestamp. Giữ mẫu cuối của mỗi
  // chuỗi trong tooltip; toàn bộ điểm vẫn được vẽ trên biểu đồ.
  const latest = new Map<number, TooltipParam>();
  const counts = new Map<number, number>();
  for (const p of params) {
    latest.set(p.seriesIndex, p);
    counts.set(p.seriesIndex, (counts.get(p.seriesIndex) ?? 0) + 1);
  }
  const rows = [...latest.values()].map((p) => {
    const s = series[p.seriesIndex];
    const v = formatNumber(p.value[1], s.digits);
    return `<div class="chart-tooltip__row"><span>${p.marker}${escapeHtml(s.name)}</span><strong>${v}<small>${v === EMPTY ? "" : ` ${escapeHtml(s.unit)}`}</small></strong></div>`;
  });
  const batchSize = Math.max(...counts.values());
  const note = batchSize > 1 ? `<div class="chart-tooltip__time">Nhiều mẫu cùng thời điểm · Hiển thị mẫu cuối</div>` : "";
  return `<div class="chart-tooltip__time">${escapeHtml(time)}</div>${rows.join("")}${note}`;
}

/** Chống chèn HTML vào tooltip (ECharts render tooltip bằng innerHTML). */
function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}
