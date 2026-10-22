import { Compass } from "lucide-react";
import { BrowserRouter, Link, Route, Routes } from "react-router";
import { EmptyState } from "@/components/common/EmptyState";
import { PageHeader } from "@/components/layout/PageHeader";
import { AppLayout } from "@/layouts/AppLayout";
import { SensorDashboard } from "@/pages/SensorDashboard";

/** Định tuyến các trang. Bản đồ và Lịch sử sẽ thay trang tạm ở bước 3, 4. */
export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppLayout />}>
          <Route index element={<SensorDashboard />} />
          <Route path="map" element={<ComingSoon title="Bản đồ chất lượng không khí" />} />
          <Route path="history" element={<ComingSoon title="Lịch sử dữ liệu" />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

/** Trang tạm cho mục chưa làm. */
function ComingSoon({ title }: { title: string }) {
  return (
    <>
      <PageHeader title={title} />
      <EmptyState icon={Compass} title="Đang xây dựng">
        Trang này sẽ được hoàn thiện ở bước tiếp theo.
      </EmptyState>
    </>
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
