import {
  Activity,
  BatteryMedium,
  Cloud,
  CloudFog,
  Droplets,
  RadioTower,
  RefreshCw,
  ServerCrash,
  Thermometer,
  Wind,
} from "lucide-react";
import { useCallback, useMemo, useState } from "react";
import { useSearchParams } from "react-router";
import { fetchNodes, fetchReadings } from "@/api/dev";
import type { NodeInfo, NodeReadings, RangeHours, Reading } from "@/api/types";
import { AqiCard } from "@/components/aqi/AqiCard";
import { AqiScale } from "@/components/aqi/AqiScale";
import { HealthAdvice } from "@/components/aqi/HealthAdvice";
import { WhoBand } from "@/components/aqi/WhoBand";
import { type ChartSeries, SeriesChart } from "@/components/charts/SeriesChart";
import { EmptyState } from "@/components/common/EmptyState";
import { StatusBanner } from "@/components/common/StatusBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { RefreshControl } from "@/components/layout/RefreshControl";
import { MetricCard } from "@/components/metrics/MetricCard";
import { usePolling } from "@/hooks/usePolling";
import { aqiLevel } from "@/lib/aqi";
import { formatAge, formatClock, formatDateTime, formatDuration, formatNumber } from "@/lib/format";

const POLL_MS = 10_000; // SSE chưa có: làm mới bằng polling 10 giây
const RANGES: RangeHours[] = [1, 6, 24];
const GAS_NOT_READY = 1 << 2; // qc_flags bit 2: CCS811 báo CO₂ = 0 (đang khởi động)

const STATUS_LABEL: Record<string, string> = {
  pending: "Chờ duyệt",
  active: "Đã duyệt",
  maintenance: "Bảo trì",
  disabled: "Đã tắt",
  retired: "Ngưng hoạt động",
};
const TIME_SOURCE_LABEL: Record<string, string> = {
  received: "theo thời điểm nhận",
  estimated: "ước lượng theo chu kỳ",
  unreliable: "không chắc chắn (dữ liệu gửi bù)",
  device: "do thiết bị gửi",
};

interface DashboardData {
  nodes: NodeInfo[];
  detail: NodeReadings | null;
}

/**
 * Trang Tổng quan kiểu IQAir: phần đầu có thẻ AQI theo màu US EPA, thẻ thông số và thiết bị, so sánh WHO,
 * khuyến nghị sức khỏe, thang AQI và biểu đồ của node đang chọn; làm mới mỗi 10 giây.
 */
export function SensorDashboard() {
  // Node đang xem nằm trên URL (?node=) để mở thẳng từ Bản đồ, Lịch sử
  const [params, setParams] = useSearchParams();
  const selectedId = Number(params.get("node")) || null;
  const setSelectedId = (id: number) => setParams({ node: String(id) }, { replace: true });
  const [hours, setHours] = useState<RangeHours>(1);

  // Mỗi lượt: lấy danh sách node, rồi số đo của node đang chọn (mặc định node đầu tiên)
  const load = useCallback(
    async (signal: AbortSignal): Promise<DashboardData> => {
      const nodes = await fetchNodes(signal);
      const node = nodes.find((n) => n.id === selectedId) ?? nodes[0];
      const detail = node ? await fetchReadings(node.id, hours, signal) : null;
      return { nodes, detail };
    },
    [selectedId, hours],
  );
  const { data, error, loading, lastSuccessAt, refresh } = usePolling(load, `${selectedId}-${hours}`, POLL_MS);

  const detail = data?.detail ?? null;
  const charts = useMemo(() => (detail ? buildCharts(detail) : null), [detail]);
  const refreshControl = <RefreshControl lastSuccessAt={lastSuccessAt} loading={loading} onRefresh={refresh} />;

  if (!data) {
    const devOff = error?.code === "HTTP_404";
    return (
      <>
        <PageHeader eyebrow="Tổng quan" title="Chất lượng không khí" actions={refreshControl} />
        {error ? (
          <EmptyState
            icon={ServerCrash}
            title={devOff ? "API dev chưa được bật" : "Mất kết nối tới máy chủ"}
            action={
              <button type="button" className="btn btn--primary" onClick={refresh}>
                <RefreshCw size={16} aria-hidden="true" /> Thử lại
              </button>
            }
          >
            {devOff
              ? "Backend cần chạy với ENABLE_DEV_ENDPOINTS=true (docker-compose.dev.yml)."
              : `${error.message}. Tự thử lại sau mỗi 10 giây.`}
          </EmptyState>
        ) : (
          <LoadingSkeleton />
        )}
      </>
    );
  }

  if (!detail) {
    return (
      <>
        <PageHeader eyebrow="Tổng quan" title="Chất lượng không khí" actions={refreshControl} />
        <EmptyState icon={RadioTower} title="Chưa có node nào">
          Chưa có node nào gửi dữ liệu hoặc được đăng ký. Trang sẽ tự cập nhật khi Gateway gửi số đo đầu tiên.
        </EmptyState>
      </>
    );
  }

  const { node, latest, units } = detail;
  const stale = Boolean(latest && node.freshness.is_stale);
  const level = aqiLevel(latest?.aqi_instant);
  const gasNote = latest && latest.co2 === null && latest.qc_flags & GAS_NOT_READY ? "CCS811 đang khởi động" : undefined;

  return (
    <main className="overview">
      <section className="ov-hero" style={{ "--lvl-soft": level?.soft ?? "var(--surface-muted)" } as React.CSSProperties}>
        <div className="ov-hero__text">
          <p className="ov-hero__crumbs">
            Trạm quan trắc / {node.station_code} / <strong>{node.device_code}</strong>
          </p>
          <h1>Chất lượng không khí tại {node.name}</h1>
          <p className="ov-hero__sub">
            Chỉ số AQI Mỹ và các thông số đo
            {latest && ` · số đo mới nhất ${formatDateTime(node.freshness.last_received_at)}`}
          </p>
          <div className="ov-hero__actions">{refreshControl}</div>
        </div>
        <AqiCard latest={latest} units={units} stale={stale} />
      </section>

      {data.nodes.length > 1 && (
        <label className="field field--inline">
          <span>Node</span>
          <select value={node.id} onChange={(e) => setSelectedId(Number(e.target.value))}>
            {data.nodes.map((n) => (
              <option key={n.id} value={n.id}>
                {n.device_code} · {n.station_code}
              </option>
            ))}
          </select>
        </label>
      )}

      <Banners detail={detail} error={Boolean(error)} lastSuccessAt={lastSuccessAt} />

      <div className="ov-grid">
        <section className="card" aria-labelledby="metrics-title">
          <h2 id="metrics-title" className="card__title">
            Các thông số đo
          </h2>
          <p className="card__sub">Số đo mới nhất · "—" là cảm biến không có số đo hợp lệ</p>
          <div className="metrics">
            <MetricCard label="PM2.5" value={latest?.pm25} unit={units.pm25} icon={CloudFog} hint="Hạt mịn (≤ 2,5 µm)" />
            <MetricCard label="PM10" value={latest?.pm10} unit={units.pm10} icon={Cloud} hint="Hạt lớn (≤ 10 µm)" />
            <MetricCard label="Nhiệt độ" value={latest?.temperature} unit={units.temperature} icon={Thermometer} hint="Không khí" />
            <MetricCard label="Độ ẩm" value={latest?.humidity} unit={units.humidity} icon={Droplets} hint="Độ ẩm tương đối" />
          </div>
          <div className="metrics metrics--minor">
            <MetricCard minor label="eCO₂" value={latest?.co2} unit={units.co2} digits={0} icon={Wind} hint={gasNote ?? "CO₂ tương đương"} />
            <MetricCard minor label="TVOC" value={latest?.tvoc} unit={units.tvoc} digits={0} icon={Activity} hint={gasNote ?? "Hợp chất hữu cơ bay hơi"} />
          </div>
        </section>
        <DevicePanel node={node} latest={latest} />
      </div>

      <WhoBand pm25={latest?.pm25} />

      <div className="ov-grid ov-grid--even">
        <HealthAdvice level={level} stale={stale} />
        <section className="card" aria-labelledby="scale-title">
          <h2 id="scale-title" className="card__title">
            Thang AQI Mỹ
          </h2>
          <p className="card__sub">Màu theo 6 mức của US EPA</p>
          <AqiScale current={level} vertical />
        </section>
      </div>

      {charts && (
        <section className="section" aria-labelledby="charts-title">
          <header className="section__head section__head--row">
            <div>
              <h2 id="charts-title">Biến động theo thời gian</h2>
              <p className="section__sub">
                {detail.readings.length.toLocaleString("vi-VN")} số đo trong {hours} giờ qua
                {detail.truncated && " (đã giới hạn số điểm)"}
              </p>
            </div>
            <div className="segmented" role="group" aria-label="Khoảng thời gian">
              {RANGES.map((h) => (
                <button key={h} type="button" aria-pressed={hours === h} onClick={() => setHours(h)}>
                  {h} giờ
                </button>
              ))}
            </div>
          </header>
          <div className="charts">
            <ChartCard title="Bụi mịn PM2.5 / PM10" wide>
              <SeriesChart title="Bụi mịn" series={charts.pm} emptyText={`Chưa có số đo PM trong ${hours} giờ qua`} />
            </ChartCard>
            <ChartCard title="Khí: eCO₂ và TVOC">
              <SeriesChart title="Khí" series={charts.gas} emptyText={`Chưa có số đo khí hợp lệ trong ${hours} giờ qua`} />
            </ChartCard>
            <ChartCard title="Nhiệt độ và độ ẩm">
              <SeriesChart
                title="Nhiệt độ và độ ẩm"
                series={charts.climate}
                emptyText={`Chưa có số đo nhiệt độ/độ ẩm trong ${hours} giờ qua`}
              />
            </ChartCard>
          </div>
        </section>
      )}
    </main>
  );
}

/** Các dải thông báo trạng thái: mất kết nối, chưa có dữ liệu, dữ liệu cũ, node chờ duyệt, dữ liệu cách ly. */
function Banners({ detail, error, lastSuccessAt }: { detail: NodeReadings; error: boolean; lastSuccessAt: Date | null }) {
  const { node, latest } = detail;
  return (
    <div className="banners" aria-live="polite">
      {error && (
        <StatusBanner tone="offline" title="Mất kết nối tới máy chủ">
          Đang hiển thị dữ liệu tải lúc {lastSuccessAt ? formatClock(lastSuccessAt) : "—"}. Tự thử lại sau 10 giây.
        </StatusBanner>
      )}
      {!latest && (
        <StatusBanner tone="info" title="Chưa có dữ liệu">
          Node đã đăng ký nhưng chưa có số đo nào được lưu.
        </StatusBanner>
      )}
      {latest && node.freshness.is_stale && (
        <StatusBanner tone="warning" title="Dữ liệu cũ">
          Số đo gần nhất nhận được {formatAge(node.freshness.age_s)} (ngưỡng {formatDuration(node.freshness.stale_after_s)}).
          Các giá trị bên dưới là số đo cuối cùng.
        </StatusBanner>
      )}
      {node.status === "pending" && (
        <StatusBanner tone="info" title="Node đang chờ duyệt">
          Node chưa được Admin duyệt nên chưa công khai; dữ liệu chỉ xem được qua API dev.
        </StatusBanner>
      )}
      {latest?.quarantined && (
        <StatusBanner tone="warning" title="Dữ liệu đang cách ly">
          Số đo đi qua Gateway chưa được duyệt; không dùng cho tổng hợp và cảnh báo cho tới khi Gateway được duyệt.
        </StatusBanner>
      )}
    </div>
  );
}

/** Thẻ thiết bị: node, Gateway, thời điểm nhận gần nhất, trạng thái cập nhật và pin. */
function DevicePanel({ node, latest }: { node: NodeInfo; latest: Reading | null }) {
  const gw = node.gateway;
  const fresh = latest && !node.freshness.is_stale;
  const battery = latest?.battery_pct ?? node.battery_pct;
  return (
    <section className="card device" aria-label="Thông tin thiết bị">
      <h2 className="card__title">Thiết bị</h2>
      <dl className="device__list">
        <div>
          <dt>Trạng thái cập nhật</dt>
          <dd className={fresh ? "text-ok" : "text-warn"}>
            <span className={`dot ${fresh ? "dot--ok" : "dot--warn"}`} aria-hidden="true" />
            {!latest ? "Chưa có dữ liệu" : fresh ? "Đang nhận dữ liệu" : "Dữ liệu cũ"}
          </dd>
        </div>
        <div>
          <dt>Nhận gần nhất</dt>
          <dd>
            {formatDateTime(node.freshness.last_received_at)}
            <small>{formatAge(node.freshness.age_s)}</small>
          </dd>
        </div>
        <div>
          <dt>Node</dt>
          <dd>
            {node.device_code}
            <span className={`tag tag--${node.status}`}>{STATUS_LABEL[node.status] ?? node.status}</span>
          </dd>
        </div>
        <div>
          <dt>Gateway</dt>
          <dd>
            {gw ? gw.id : "—"}
            {gw && (
              <>
                <span className={`tag tag--${gw.status}`}>{STATUS_LABEL[gw.status] ?? gw.status}</span>
                <small>
                  <span className={`dot ${gw.online ? "dot--ok" : "dot--off"}`} aria-hidden="true" />{" "}
                  {gw.online ? "Trực tuyến" : "Mất liên lạc"}
                </small>
              </>
            )}
          </dd>
        </div>
        <div>
          <dt>Pin</dt>
          <dd>
            <BatteryMedium size={16} aria-hidden="true" /> {formatNumber(battery, 0)}
            {battery != null && " %"}
          </dd>
        </div>
        <div>
          <dt>Thời điểm đo</dt>
          <dd>{latest ? (TIME_SOURCE_LABEL[latest.time_source] ?? latest.time_source) : "—"}</dd>
        </div>
      </dl>
    </section>
  );
}

/** Khung chứa một biểu đồ. */
function ChartCard({ title, children, wide }: { title: string; children: React.ReactNode; wide?: boolean }) {
  return (
    <article className={`panel ${wide ? "panel--wide" : ""}`}>
      <h3 className="panel__title">{title}</h3>
      {children}
    </article>
  );
}

/** Khung xương khi đang tải lần đầu, giữ chỗ để bố cục không nhảy. */
function LoadingSkeleton() {
  return (
    <div className="overview" aria-busy="true" aria-label="Đang tải dữ liệu">
      <div className="ov-grid">
        <div className="skeleton skeleton--hero" />
        <div className="skeleton skeleton--hero" />
      </div>
      <div className="metrics">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="skeleton skeleton--metric" />
        ))}
      </div>
      <div className="skeleton skeleton--chart" />
    </div>
  );
}

/** Dữ liệu cho 3 biểu đồ; đại lượng khác đơn vị nằm ở hai trục y khác nhau. */
function buildCharts({ readings, units }: NodeReadings): Record<"pm" | "gas" | "climate", ChartSeries[]> {
  const series = (key: keyof Reading) =>
    readings.map((r): [number, number | null] => [Date.parse(r.measured_at), r[key] as number | null]);
  return {
    pm: [
      { name: "PM2.5", unit: units.pm25, color: "#1D4ED8", axis: 0, digits: 1, points: series("pm25") },
      { name: "PM10", unit: units.pm10, color: "#0E7490", axis: 0, digits: 1, points: series("pm10") },
    ],
    gas: [
      { name: "eCO₂", unit: units.co2, color: "#7C3AED", axis: 0, digits: 0, points: series("co2") },
      { name: "TVOC", unit: units.tvoc, color: "#C2410C", axis: 1, digits: 0, points: series("tvoc") },
    ],
    climate: [
      { name: "Nhiệt độ", unit: units.temperature, color: "#DC2626", axis: 0, digits: 1, points: series("temperature") },
      { name: "Độ ẩm", unit: units.humidity, color: "#0369A1", axis: 1, digits: 1, points: series("humidity") },
    ],
  };
}
