import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

/** Khung trạng thái toàn trang: chưa có dữ liệu, lỗi, mất kết nối. */
export function EmptyState({
  icon: Icon,
  title,
  children,
  action,
}: {
  icon: LucideIcon;
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <section className="empty-state" role="status">
      <Icon size={40} aria-hidden="true" className="empty-state__icon" />
      <h2>{title}</h2>
      {children && <p>{children}</p>}
      {action}
    </section>
  );
}
