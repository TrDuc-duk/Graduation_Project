import { AlertTriangle, CircleAlert, Info, WifiOff } from "lucide-react";
import type { ReactNode } from "react";

type Tone = "info" | "warning" | "danger" | "offline";

const ICONS = { info: Info, warning: AlertTriangle, danger: CircleAlert, offline: WifiOff };

/** Dải thông báo trạng thái (mất kết nối, dữ liệu cũ, cách ly...). Có icon + chữ, không chỉ dựa vào màu. */
export function StatusBanner({ tone, title, children }: { tone: Tone; title: string; children?: ReactNode }) {
  const Icon = ICONS[tone];
  return (
    <div className={`banner banner--${tone}`} role={tone === "danger" || tone === "offline" ? "alert" : "status"}>
      <Icon className="banner__icon" aria-hidden="true" size={20} />
      <div>
        <p className="banner__title">{title}</p>
        {children && <p className="banner__text">{children}</p>}
      </div>
    </div>
  );
}
