import { CircleAlert, CircleCheck } from "lucide-react";
import { formatNumber } from "@/lib/format";

// Giá trị hướng dẫn hằng năm về PM2.5 của WHO (Air Quality Guidelines 2021)
const WHO_PM25_ANNUAL = 5;

/** Dải so sánh PM2.5 hiện tại với giá trị hướng dẫn hằng năm của WHO (giống IQAir); không có PM2.5 thì ẩn. */
export function WhoBand({ pm25 }: { pm25: number | null | undefined }) {
  if (pm25 == null) return null;
  const ratio = pm25 / WHO_PM25_ANNUAL;
  const over = ratio > 1;
  const Icon = over ? CircleAlert : CircleCheck;
  return (
    <p className={`who-band ${over ? "who-band--over" : ""}`}>
      <Icon size={20} aria-hidden="true" className="who-band__icon" />
      <span>
        Nồng độ <strong>PM2.5</strong>{" "}
        {over ? (
          <>
            hiện tại gấp <strong className="who-band__ratio">{formatNumber(ratio, 1)}</strong> lần
          </>
        ) : (
          "hiện tại không vượt"
        )}{" "}
        giá trị hướng dẫn hằng năm về PM2.5 của WHO ({WHO_PM25_ANNUAL} µg/m³).
      </span>
    </p>
  );
}
