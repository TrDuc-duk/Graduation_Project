import { MapPinOff, RadioTower, RefreshCw, ServerCrash } from "lucide-react";
import { useCallback } from "react";
import { useSearchParams } from "react-router";
import { fetchNodes } from "@/api/dev";
import type { NodeInfo } from "@/api/types";
import { EmptyState } from "@/components/common/EmptyState";
import { StatusBanner } from "@/components/common/StatusBanner";
import { PageHeader } from "@/components/layout/PageHeader";
import { RefreshControl } from "@/components/layout/RefreshControl";
import { StationMap } from "@/components/map/StationMap";
import { usePolling } from "@/hooks/usePolling";
import { aqiLevel } from "@/lib/aqi";
import { EMPTY, formatAge, formatClock, formatNumber } from "@/lib/format";

const POLL_MS = 10_000;

/** Trạm xếp theo AQI giảm dần (ô nhiễm nhất lên đầu); trạm chưa có AQI xuống cuối. */
function byAqiDesc(a: NodeInfo, b: NodeInfo): number {
  return (b.latest?.aqi_instant ?? -1) - (a.latest?.aqi_instant ?? -1);
}

/**
 * Trang Bản đồ kiểu IQAir: bản đồ lớn với marker màu AQI của các trạm, bấm marker xem popup;
 * dưới bản đồ là danh sách trạm xếp theo AQI, bấm một dòng để mở trạm trên bản đồ. Làm mới mỗi 10 giây.
 */
export function MapPage() {
  const [params, setParams] = useSearchParams();
  const selectedId = Number(params.get("node")) || null;
  const select = useCallback(
    (id: number | null) => setParams(id ? { node: String(id) } : {}, { replace: true }),
    [setParams],
  );

  const { data, error, loading, lastSuccessAt, refresh } = usePolling(fetchNodes, "nodes", POLL_MS);
  const stations = data ? [...data].sort(byAqiDesc) : [];
  const placed = stations.filter((s) => s.latitude != null && s.longitude != null).length;

  return (
    <>
      <PageHeader
        eyebrow="Bản đồ"
        title="Bản đồ chất lượng không khí"
        subtitle={
          data
            ? `Chỉ số AQI Mỹ tức thời tại các trạm quan trắc · ${stations.length} trạm, ${placed} trạm có tọa độ`
            : "Chỉ số AQI Mỹ tức thời tại các trạm quan trắc"
        }
        actions={<RefreshControl lastSuccessAt={lastSuccessAt} loading={loading} onRefresh={refresh} />}
      />

      {!data && error && (
        <EmptyState
          icon={ServerCrash}
          title="Mất kết nối tới máy chủ"
          action={
            <button type="button" className="btn btn--primary" onClick={refresh}>
              <RefreshCw size={16} aria-hidden="true" /> Thử lại
            </button>
          }
        >
          {error.message}. Tự thử lại sau mỗi 10 giây.
        </EmptyState>
      )}
      {!data && !error && <div className="skeleton skeleton--map" aria-busy="true" aria-label="Đang tải bản đồ" />}

      {data && (
        <main className="overview">
          {error && (
            <StatusBanner tone="offline" title="Mất kết nối tới máy chủ">
              Đang hiển thị dữ liệu tải lúc {lastSuccessAt ? formatClock(lastSuccessAt) : EMPTY}. Tự thử lại sau 10 giây.
            </StatusBanner>
          )}
          <StationMap stations={stations} selectedId={selectedId} onSelect={select} />
          {stations.length === 0 ? (
            <EmptyState icon={RadioTower} title="Chưa có trạm nào">
              Trạm xuất hiện khi Gateway gửi số đo đầu tiên của node.
            </EmptyState>
          ) : (
            <StationList stations={stations} selectedId={selectedId} onSelect={select} />
          )}
        </main>
      )}
    </>
  );
}

/** Danh sách trạm xếp theo AQI: ô màu AQI, tên, mã, PM2.5, độ mới dữ liệu và nhãn trạng thái. */
function StationList({
  stations,
  selectedId,
  onSelect,
}: {
  stations: NodeInfo[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  return (
    <section className="card" aria-labelledby="stations-title">
      <h2 id="stations-title" className="card__title">
        Các trạm quan trắc
      </h2>
      <p className="card__sub">Xếp theo AQI Mỹ tức thời, cao nhất ở đầu · bấm một trạm để xem trên bản đồ</p>
      <ol className="station-list">
        {stations.map((s) => {
          const level = aqiLevel(s.latest?.aqi_instant);
          const hasPosition = s.latitude != null && s.longitude != null;
          return (
            <li key={s.id}>
              <button
                type="button"
                className="station-row"
                aria-current={s.id === selectedId ? "true" : undefined}
                onClick={() => {
                  onSelect(s.id);
                  if (hasPosition) document.querySelector(".map")?.scrollIntoView({ behavior: "smooth", block: "center" });
                }}
              >
                <span className="station-row__aqi" style={level ? { background: level.color, color: level.text } : undefined}>
                  {s.latest?.aqi_instant ?? EMPTY}
                </span>
                <span className="station-row__name">
                  <strong>{s.name}</strong>
                  <small>
                    {s.station_code} · {s.device_code}
                    {s.district && ` · ${s.district}`}
                  </small>
                </span>
                <span className="station-row__value">
                  PM2.5 <strong>{formatNumber(s.latest?.pm25)}</strong>
                </span>
                <span className="station-row__tags">
                  <small>{formatAge(s.freshness.age_s)}</small>
                  {s.freshness.is_stale && s.latest && <span className="tag tag--pending">Dữ liệu cũ</span>}
                  {s.status === "pending" && <span className="tag tag--pending">Chờ duyệt</span>}
                  {!hasPosition && (
                    <span className="tag tag--muted">
                      <MapPinOff size={12} aria-hidden="true" /> Chưa có tọa độ
                    </span>
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
