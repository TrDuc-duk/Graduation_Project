import { Bike, Blinds, Fan, type LucideIcon, ShieldCheck, TreePine, Users } from "lucide-react";
import type { AqiLevel } from "@/lib/aqi";

interface Advice {
  icon: LucideIcon;
  text: string;
}

// Khuyến nghị chung theo mức AQI Mỹ (theo hướng dẫn của US EPA, giống mục "Khuyến nghị về sức khoẻ" của IQAir)
const ADVICE: Record<string, Advice[]> = {
  good: [
    { icon: TreePine, text: "Thích hợp cho các hoạt động ngoài trời" },
    { icon: Blinds, text: "Có thể mở cửa sổ đón không khí trong lành" },
  ],
  moderate: [
    { icon: Users, text: "Người nhạy cảm nên giảm vận động mạnh ngoài trời" },
    { icon: Blinds, text: "Người nhạy cảm nên đóng cửa sổ khi không khí bên ngoài kém" },
  ],
  usg: [
    { icon: Bike, text: "Giảm vận động mạnh ngoài trời" },
    { icon: Blinds, text: "Đóng cửa sổ để tránh không khí bẩn bên ngoài" },
    { icon: ShieldCheck, text: "Nhóm nhạy cảm nên đeo khẩu trang khi ra ngoài" },
    { icon: Fan, text: "Bật máy lọc không khí nếu có" },
  ],
  unhealthy: [
    { icon: Bike, text: "Tránh vận động mạnh ngoài trời" },
    { icon: Blinds, text: "Đóng cửa sổ để tránh không khí bẩn bên ngoài" },
    { icon: ShieldCheck, text: "Đeo khẩu trang lọc bụi khi ra ngoài" },
    { icon: Fan, text: "Bật máy lọc không khí" },
  ],
  very_unhealthy: [
    { icon: Bike, text: "Tránh mọi hoạt động ngoài trời" },
    { icon: Blinds, text: "Đóng kín cửa sổ" },
    { icon: ShieldCheck, text: "Đeo khẩu trang lọc bụi khi buộc phải ra ngoài" },
    { icon: Fan, text: "Bật máy lọc không khí" },
  ],
  hazardous: [
    { icon: Bike, text: "Ở trong nhà, tránh mọi hoạt động ngoài trời" },
    { icon: Blinds, text: "Đóng kín cửa sổ" },
    { icon: ShieldCheck, text: "Đeo khẩu trang lọc bụi khi buộc phải ra ngoài" },
    { icon: Fan, text: "Bật máy lọc không khí" },
  ],
};

/** Thẻ khuyến nghị sức khỏe theo mức AQI của số đo mới nhất; dữ liệu cũ thì ghi rõ khuyến nghị theo số đo cuối. */
export function HealthAdvice({ level, stale }: { level: AqiLevel | null; stale: boolean }) {
  return (
    <section className="card" aria-labelledby="advice-title">
      <h2 id="advice-title" className="card__title">
        Khuyến nghị về sức khỏe
      </h2>
      {level ? (
        <>
          {stale && <p className="card__sub">Theo số đo cuối cùng (dữ liệu cũ).</p>}
          <ul className="advice">
            {ADVICE[level.key].map(({ icon: Icon, text }) => (
              <li key={text}>
                <span className="advice__icon" style={{ background: level.soft, color: level.text }}>
                  <Icon size={20} aria-hidden="true" />
                </span>
                {text}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="card__sub">Chưa có AQI để đưa ra khuyến nghị.</p>
      )}
    </section>
  );
}
