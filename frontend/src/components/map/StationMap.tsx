import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { LocateFixed, Maximize2, Minimize2, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router";
import type { NodeInfo } from "@/api/types";
import { AQI_LEVELS, aqiLevel } from "@/lib/aqi";
import { EMPTY, formatDateTime, formatNumber } from "@/lib/format";

// Khung nhìn mặc định khi chưa trạm nào có tọa độ: toàn Việt Nam
const VIETNAM: L.LatLngTuple = [16.2, 106.3];
const VIETNAM_ZOOM = 5;
// Tile nền từ dữ liệu OpenStreetMap, kiểu HOT (màu dịu) do OpenStreetMap France phục vụ, không cần khóa API.
// tile.openstreetmap.org bị DNS mạng dev chặn; có thể đổi nguồn tile qua biến VITE_MAP_TILE_URL khi build.
const TILES = import.meta.env.VITE_MAP_TILE_URL ?? "https://{s}.tile.openstreetmap.fr/hot/{z}/{x}/{y}.png";
const TILE_CREDIT =
  '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · Kiểu HOT, máy chủ <a href="https://www.openstreetmap.fr/">OSM France</a>';

interface Props {
  stations: NodeInfo[];
  selectedId: number | null;
  onSelect: (id: number | null) => void;
}

/** Vị trí của trạm, hoặc null khi chưa nhập tọa độ. */
function position(n: NodeInfo): L.LatLngTuple | null {
  return n.latitude != null && n.longitude != null ? [n.latitude, n.longitude] : null;
}

/** Marker tròn màu theo mức AQI, số AQI ở giữa (giống IQAir); dữ liệu cũ thì viền đứt. */
function markerIcon(station: NodeInfo, active: boolean): L.DivIcon {
  const aqi = station.latest?.aqi_instant;
  const level = aqiLevel(aqi);
  const classes = ["map-marker", station.freshness.is_stale && "map-marker--stale", active && "map-marker--active"];
  const style = level ? `background:${level.color};color:${level.text}` : "";
  return L.divIcon({
    className: "",
    html: `<span class="${classes.filter(Boolean).join(" ")}" style="${style}">${aqi ?? EMPTY}</span>`,
    iconSize: [40, 40],
    iconAnchor: [20, 20],
  });
}

/**
 * Bản đồ trạm kiểu IQAir (Leaflet + tile OpenStreetMap): marker tròn màu theo AQI, bấm để mở popup
 * (nội dung React qua portal); nút toàn màn hình, nút về các trạm, nút zoom; chú giải 6 mức AQI ở đáy.
 */
export function StationMap({ stations, selectedId, onSelect }: Props) {
  const frameRef = useRef<HTMLDivElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layerRef = useRef<L.LayerGroup | null>(null);
  const popupRef = useRef<L.Popup | null>(null);
  const [popupEl] = useState(() => document.createElement("div"));
  const [fullscreen, setFullscreen] = useState(false);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
  const fittedRef = useRef(false);

  const selected = stations.find((s) => s.id === selectedId) ?? null;
  const selectedPos = selected ? position(selected) : null;

  // Đưa khung nhìn về vừa đủ các trạm có tọa độ (không có trạm nào thì về toàn Việt Nam)
  const fitStations = useCallback(() => {
    const map = mapRef.current;
    const points = stations.map(position).filter((p): p is L.LatLngTuple => p !== null);
    if (!map) return;
    if (points.length === 0) map.setView(VIETNAM, VIETNAM_ZOOM);
    else map.fitBounds(L.latLngBounds(points), { padding: [60, 60], maxZoom: 14 });
  }, [stations]);

  // Tạo bản đồ một lần: lớp tile nền, nút zoom góc dưới phải, popup dùng chung; gỡ khi rời trang
  useEffect(() => {
    if (!boxRef.current) return;
    const map = L.map(boxRef.current, { zoomControl: false }).setView(VIETNAM, VIETNAM_ZOOM);
    L.tileLayer(TILES, { maxZoom: 19, attribution: TILE_CREDIT }).addTo(map);
    L.control.zoom({ position: "bottomright", zoomInTitle: "Phóng to", zoomOutTitle: "Thu nhỏ" }).addTo(map);
    map.attributionControl.setPrefix(false);
    layerRef.current = L.layerGroup().addTo(map);
    popupRef.current = L.popup({ closeButton: false, offset: [0, -14], maxWidth: 300, minWidth: 240 }).setContent(popupEl);
    map.on("popupclose", () => onSelectRef.current(null));
    mapRef.current = map;
    return () => {
      map.off(); // gỡ listener trước: map.remove() đóng popup, không để nó gọi onSelect(null) khi đang rời trang
      map.remove();
      mapRef.current = null;
    };
  }, [popupEl]);

  // Vẽ lại marker mỗi lần có dữ liệu mới; lần đầu có dữ liệu thì khớp khung nhìn với các trạm
  useEffect(() => {
    const layer = layerRef.current;
    if (!layer) return;
    layer.clearLayers();
    for (const s of stations) {
      const pos = position(s);
      if (!pos) continue;
      const level = aqiLevel(s.latest?.aqi_instant);
      L.marker(pos, {
        icon: markerIcon(s, s.id === selectedId),
        title: `${s.station_code} ${s.name}: AQI ${s.latest?.aqi_instant ?? "chưa có"}${level ? `, ${level.label}` : ""}`,
        riseOnHover: true,
      })
        .on("click", () => onSelectRef.current(s.id))
        .addTo(layer);
    }
    if (!fittedRef.current) {
      fittedRef.current = true;
      fitStations();
    }
  }, [stations, selectedId, fitStations]);

  // Trạm được chọn có tọa độ: mở popup tại trạm (Leaflet tự dời bản đồ cho popup lọt khung); bỏ chọn thì đóng
  useEffect(() => {
    const map = mapRef.current;
    const popup = popupRef.current;
    if (!map || !popup) return;
    if (selectedPos) popup.setLatLng(selectedPos).openOn(map);
    else if (popup.isOpen()) map.closePopup(popup);
    // phụ thuộc vào tọa độ (số) thay vì mảng mới tạo mỗi lần polling, để popup không mở lại liên tục
  }, [selectedPos?.[0], selectedPos?.[1], selectedId]);

  // Nội dung popup (React) vừa đổi: báo Leaflet đo lại kích thước popup
  useLayoutEffect(() => {
    popupRef.current?.update();
  });

  // Vào/ra toàn màn hình (kể cả khi nhấn Esc của trình duyệt): cập nhật nút và cho Leaflet đo lại khung
  useEffect(() => {
    const onChange = () => {
      setFullscreen(document.fullscreenElement === frameRef.current);
      mapRef.current?.invalidateSize();
    };
    document.addEventListener("fullscreenchange", onChange);
    return () => document.removeEventListener("fullscreenchange", onChange);
  }, []);

  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void frameRef.current?.requestFullscreen?.();
  };

  const placedCount = stations.filter((s) => position(s)).length;

  return (
    <div ref={frameRef} className={`map ${fullscreen ? "map--fullscreen" : ""}`}>
      <div ref={boxRef} className="map__viewport" aria-label="Bản đồ trạm quan trắc" />

      <div className="map__tools">
        <button type="button" className="map-ctrl" onClick={toggleFullscreen} aria-label={fullscreen ? "Thoát toàn màn hình" : "Xem toàn màn hình"}>
          {fullscreen ? <Minimize2 size={18} aria-hidden="true" /> : <Maximize2 size={18} aria-hidden="true" />}
        </button>
        <button type="button" className="map-ctrl" onClick={fitStations} aria-label="Về các trạm">
          <LocateFixed size={18} aria-hidden="true" />
        </button>
      </div>

      {placedCount === 0 && (
        <p className="map__notice">Chưa có trạm nào được nhập tọa độ. Danh sách trạm ở bên dưới bản đồ.</p>
      )}

      <ol className="map__legend" aria-label="Chú giải AQI Mỹ">
        {AQI_LEVELS.map((l) => (
          <li key={l.key} style={{ background: l.color, color: l.text }}>
            {l.label}
          </li>
        ))}
      </ol>

      {selected && createPortal(<StationPopup station={selected} onClose={() => onSelect(null)} />, popupEl)}
    </div>
  );
}

/** Nội dung popup: AQI và mức, PM2.5, PM10, nhiệt độ, thời điểm đo, liên kết sang Tổng quan và Lịch sử. */
function StationPopup({ station, onClose }: { station: NodeInfo; onClose: () => void }) {
  const { latest } = station;
  const level = aqiLevel(latest?.aqi_instant);
  return (
    <div className="map-popup">
      <div className="map-popup__head">
        <div>
          <p className="map-popup__name">{station.name}</p>
          <p className="map-popup__code">
            {station.station_code} · {station.device_code}
            {station.district && ` · ${station.district}`}
          </p>
        </div>
        <button type="button" className="map-popup__close" onClick={onClose} aria-label="Đóng">
          <X size={16} aria-hidden="true" />
        </button>
      </div>
      <p className="map-popup__aqi" style={level ? { background: level.color, color: level.text } : undefined}>
        <strong>{latest?.aqi_instant ?? EMPTY}</strong>
        <span>{level ? level.label : "Chưa có AQI"}</span>
      </p>
      <dl className="map-popup__stats">
        <div>
          <dt>PM2.5</dt>
          <dd>{formatNumber(latest?.pm25)}</dd>
        </div>
        <div>
          <dt>PM10</dt>
          <dd>{formatNumber(latest?.pm10)}</dd>
        </div>
        <div>
          <dt>Nhiệt độ</dt>
          <dd>{formatNumber(latest?.temperature)}</dd>
        </div>
      </dl>
      <p className="map-popup__time">
        Đo lúc {formatDateTime(latest?.measured_at)}
        {station.freshness.is_stale && <span className="tag tag--pending">Dữ liệu cũ</span>}
      </p>
      <p className="map-popup__links">
        <Link to={`/?node=${station.id}`}>Tổng quan</Link>
        <Link to={`/history?node=${station.id}`}>Lịch sử</Link>
      </p>
    </div>
  );
}
