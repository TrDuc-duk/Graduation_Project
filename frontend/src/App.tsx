import { Compass } from "lucide-react";
import { BrowserRouter, Link, Route, Routes } from "react-router";
import { EmptyState } from "@/components/common/EmptyState";
import { AppLayout } from "@/layouts/AppLayout";
import { HistoryPage } from "@/pages/HistoryPage";
import { MapPage } from "@/pages/MapPage";
import { SensorDashboard } from "@/pages/SensorDashboard";

/** Định tuyến các trang: Tổng quan, Bản đồ, Lịch sử; đường dẫn lạ hiện trang không tìm thấy. */
export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<SensorDashboard />} />
          <Route path="map" element={<MapPage />} />
          <Route path="history" element={<HistoryPage />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

/** Đường dẫn không tồn tại. */
function NotFound() {
  return (
    <EmptyState
      icon={Compass}
      title="Không tìm thấy trang"
      action={
        <Link to="/" className="btn btn--primary">
          Về trang tổng quan
        </Link>
      }
    >
      Đường dẫn không tồn tại hoặc đã thay đổi.
    </EmptyState>
  );
}
