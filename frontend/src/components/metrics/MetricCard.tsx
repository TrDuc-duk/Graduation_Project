import type { LucideIcon } from "lucide-react";
import { EMPTY, formatNumber } from "@/lib/format";

interface Props {
  label: string;
  value: number | null | undefined;
  unit: string;
  digits?: number;
  icon: LucideIcon;
  hint?: string; // ghi chú nhỏ dưới giá trị (vd. nguồn dữ liệu, lý do thiếu)
}

/** Thẻ một thông số: tên, giá trị kèm đơn vị. Giá trị null hiển thị "—" và không kèm đơn vị. */
export function MetricCard({ label, value, unit, digits = 1, icon: Icon, hint }: Props) {
  const text = formatNumber(value, digits);
  const missing = text === EMPTY;
  return (
    <article className={`metric ${missing ? "metric--missing" : ""}`}>
      <header className="metric__head">
        <Icon size={18} aria-hidden="true" className="metric__icon" />
        <h3 className="metric__label">{label}</h3>
      </header>
      <p className="metric__value" aria-label={missing ? `${label}: không có dữ liệu` : `${label}: ${text} ${unit}`}>
        <span>{text}</span>
        {!missing && <span className="metric__unit">{unit}</span>}
      </p>
      <p className="metric__hint">{hint ?? (missing ? "Không có số đo hợp lệ" : "\u00a0")}</p>
    </article>
  );
}
