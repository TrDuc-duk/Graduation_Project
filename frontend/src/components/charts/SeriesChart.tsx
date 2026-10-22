import { BarChart, LineChart } from "echarts/charts";
import { AriaComponent, DataZoomComponent, GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { CanvasRenderer } from "echarts/renderers";
import { useEffect, useRef } from "react";
import { EMPTY, formatDateTime, formatDayHour, formatNumber, formatTime } from "@/lib/format";

// Chỉ nạp các phần ECharts thực sự dùng (frontend_design 2)
echarts.use([LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent, AriaComponent, DataZoomComponent, CanvasRenderer]);

export interface ChartSeries {
  name: string;
  unit: string;
  color: string;
  dashed?: boolean; // nét đứt để phân biệt đường không chỉ bằng màu
  axis: 0 | 1; // 0: trục trái, 1: trục phải (đại lượng khác đơn vị)
  digits: number;
  points: [number, number | null][]; // [thời điểm ms, giá trị]; null tạo khoảng đứt
  bar?: boolean; // vẽ dạng cột (vd. AQI theo giờ)
  colorOf?: (value: number) => string | undefined; // màu riêng từng cột theo giá trị (vd. mức AQI)
}

interface Props {
  title: string;
  series: ChartSeries[];
  emptyText: string;
  zoom?: boolean; // thanh kéo chọn đoạn thời gian (dataZoom) dưới biểu đồ, cuộn/kéo trong biểu đồ để phóng to
}

const LONG_SPAN_MS = 36 * 3600 * 1000; // khoảng dài hơn 36 giờ: nhãn trục ghi cả ngày

const AXIS_TEXT = "#475569";
const GRID_LINE = "#E2E8F0";
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Biểu đồ đường/cột theo thời gian; mỗi trục y ghi rõ đơn vị, giá trị null để đứt quãng (không nội suy). */
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
    animationDuration: 600,
    aria: { enabled: true, label: { description: title } },
    grid: { left: 8, right: 8, top: 60, bottom: zoom ? 56 : 8, containLabel: true },
    dataZoom: zoom
      ? [
          { type: "inside", filterMode: "none" },
          { type: "slider", height: 22, bottom: 8, filterMode: "none", labelFormatter: (v: number) => (Number.isFinite(v) ? formatDayHour(v) : "") },
        ]
      : undefined,
    legend: { top: 0, left: 0, icon: "roundRect", itemWidth: 18, textStyle: { color: AXIS_TEXT, fontSize: 13 } },
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "line" },
      formatter: (params: unknown) => tooltipHtml(params as TooltipParam[], series),
    },
    xAxis: {
      type: "time",
      axisLabel: { color: AXIS_TEXT, formatter: (v: number) => (long ? formatDayHour(v) : formatTime(v)), hideOverlap: true },
      axisLine: { lineStyle: { color: GRID_LINE } },
      splitLine: { show: false },
    },
    yAxis: axes.map((a) => {
      const onAxis = series.filter((s) => s.axis === a);
      return {
        type: "value",
        position: a === 0 ? "left" : "right",
        name: withUnit(onAxis.map((s) => s.name).join(" / "), onAxis[0].unit),
        nameTextStyle: { color: onAxis.length === 1 ? onAxis[0].color : AXIS_TEXT, fontWeight: 600, align: a === 0 ? "left" : "right" },
        scale: true,
        axisLabel: { color: AXIS_TEXT },
        splitLine: { show: a === 0, lineStyle: { color: GRID_LINE } },
      };
    }),
    series: series.map((s) => ({
      name: s.name,
      type: s.bar ? "bar" : "line",
      yAxisIndex: axes.indexOf(s.axis),
      data: s.points,
      color: s.color, // màu ở chú giải (cột AQI tô màu riêng từng cột)
      connectNulls: false,
      showSymbol: s.points.filter(([, v]) => v !== null).length < 60, // ít điểm có giá trị: hiện chấm để thấy rõ
      symbolSize: 5,
      barMaxWidth: 14,
      barMinWidth: 3, // khoảng dài (720 giờ) vẫn thấy được cột
      lineStyle: { width: 2, type: s.dashed ? "dashed" : "solid", color: s.color },
      itemStyle: {
        color: s.colorOf
          ? (p: { value: [number, number | null] }) => (p.value[1] === null ? s.color : (s.colorOf!(p.value[1]) ?? s.color))
          : s.color,
        borderRadius: s.bar ? [3, 3, 0, 0] : 0,
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
  const rows = params.map((p) => {
    const s = series[p.seriesIndex];
    const v = formatNumber(p.value[1], s.digits);
    return `${p.marker}${escapeHtml(s.name)}: <b>${v}</b>${v === EMPTY ? "" : ` ${escapeHtml(s.unit)}`}`;
  });
  return [`<b>${time}</b>`, ...rows].join("<br/>");
}

/** Chống chèn HTML vào tooltip (ECharts render tooltip bằng innerHTML). */
function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}
