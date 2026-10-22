import { BarChart3, LayoutDashboard, Map, Menu, Wind, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router";

// Các trang có trên thanh điều hướng
const NAV_ITEMS = [
  { to: "/", label: "Tổng quan", icon: LayoutDashboard },
  { to: "/map", label: "Bản đồ", icon: Map },
  { to: "/history", label: "Lịch sử", icon: BarChart3 },
];

interface Indicator {
  left: number;
  width: number;
  visible: boolean;
}

/**
 * Thanh điều hướng trên cùng kiểu IQAir: dính khi cuộn (thêm bóng nhẹ), gạch chân trượt tới mục đang
 * hover/focus rồi trở về mục đang chọn; điện thoại thu menu vào nút ☰, đóng bằng Esc hoặc khi đổi trang.
 */
export function Topbar() {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const [indicator, setIndicator] = useState<Indicator>({ left: 0, width: 0, visible: false });
  const { pathname } = useLocation();
  const navRef = useRef<HTMLElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);

  // Đặt gạch chân dưới một mục menu (hoặc mục đang chọn khi không truyền)
  const moveIndicator = useCallback((target?: HTMLElement | null) => {
    const el = target ?? navRef.current?.querySelector<HTMLElement>(".appbar__link.active");
    setIndicator(el ? { left: el.offsetLeft, width: el.offsetWidth, visible: true } : (i) => ({ ...i, visible: false }));
  }, []);

  // Đổi trang: đóng menu điện thoại, gạch chân về mục mới; đổi kích thước cửa sổ: tính lại vị trí
  useLayoutEffect(() => {
    setOpen(false);
    moveIndicator();
    const onResize = () => moveIndicator();
    void document.fonts?.ready.then(onResize); // font tải xong thì chữ đổi rộng, đo lại
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [pathname, moveIndicator]);

  // Cuộn trang: thêm bóng nhẹ dưới topbar
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 4);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Menu điện thoại đang mở: Esc để đóng và trả focus về nút ☰
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        toggleRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <header className={`appbar ${scrolled ? "appbar--scrolled" : ""}`}>
      <div className="appbar__inner">
        <NavLink to="/" className="appbar__brand" aria-label="Giám sát Không khí — trang tổng quan">
          <span className="appbar__logo" aria-hidden="true">
            <Wind size={20} />
          </span>
          <span>
            Giám sát <strong>Không khí</strong>
          </span>
        </NavLink>

        <button
          ref={toggleRef}
          type="button"
          className="appbar__toggle"
          aria-expanded={open}
          aria-controls="main-nav"
          aria-label={open ? "Đóng menu" : "Mở menu"}
          onClick={() => setOpen((v) => !v)}
        >
          {open ? <X size={22} aria-hidden="true" /> : <Menu size={22} aria-hidden="true" />}
        </button>

        <nav
          ref={navRef}
          id="main-nav"
          className={`appbar__nav ${open ? "appbar__nav--open" : ""}`}
          aria-label="Điều hướng chính"
          onMouseLeave={() => moveIndicator()}
          onBlur={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget)) moveIndicator();
          }}
        >
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className="appbar__link"
              onMouseEnter={(e) => moveIndicator(e.currentTarget)}
              onFocus={(e) => moveIndicator(e.currentTarget)}
            >
              <Icon size={18} aria-hidden="true" />
              {label}
            </NavLink>
          ))}
          <span
            className="appbar__indicator"
            aria-hidden="true"
            style={{
              width: indicator.width,
              transform: `translateX(${indicator.left}px)`,
              opacity: indicator.visible ? 1 : 0,
            }}
          />
        </nav>

        <span className="appbar__env" title="Dữ liệu qua API dev, gồm cả thiết bị chưa duyệt">
          Môi trường dev
        </span>
      </div>
    </header>
  );
}
