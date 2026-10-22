import { Loader2, RefreshCw } from "lucide-react";
import { formatClock } from "@/lib/format";

/** Chỉ báo lần cập nhật gần nhất + nút làm mới (dùng chung cho các trang có polling). */
export function RefreshControl({
  lastSuccessAt,
  loading,
  onRefresh,
}: {
  lastSuccessAt: Date | null;
  loading: boolean;
  onRefresh: () => void;
}) {
  return (
    <>
      <p className="sync" aria-live="polite">
        {loading ? "Đang cập nhật…" : lastSuccessAt ? `Cập nhật lúc ${formatClock(lastSuccessAt)}` : "Chưa tải dữ liệu"}
        <span className="sync__sub">Tự làm mới mỗi 10 giây</span>
      </p>
      <button type="button" className="btn btn--primary" onClick={onRefresh} disabled={loading} aria-label="Làm mới dữ liệu">
        {loading ? <Loader2 size={16} className="spin" aria-hidden="true" /> : <RefreshCw size={16} aria-hidden="true" />}
        Làm mới
      </button>
    </>
  );
}
