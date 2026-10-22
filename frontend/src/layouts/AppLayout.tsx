import { Outlet } from "react-router";
import { Topbar } from "@/components/layout/Topbar";

/** Khung chung của mọi trang: topbar cố định phía trên, nội dung trang ở giữa. */
export function AppLayout() {
  return (
    <>
      <Topbar />
      <div className="page">
        <Outlet />
      </div>
    </>
  );
}
