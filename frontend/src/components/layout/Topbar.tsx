import { BarChart3, LayoutDashboard, Map, Menu, Wind, X } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { NavLink, useLocation } from "react-router";

// Các trang có trên thanh điều hướng
const NAV_ITEMS = [
  { to: "/", label: "Tổng quan", icon: LayoutDashboard },
  { to: "/map", label: "Bản đồ", icon: Map },
  { to: "/history", label: "Lịch sử", icon: BarChart3 },
];

interface Pill {
  to: string | null; // tab đang nằm dưới pill (null = chưa đo được)
  onActive: boolean; // pill đang nằm ở tab đang chọn (nền xanh lá) hay tab đang hover (nền tối)
  left: number;
  top: number;
  width: number;
  height: number;
}

/**
 * Thanh điều hướng trên cùng kiểu IQAir: dính khi cuộn (thêm bóng nhẹ). Một pill trượt tới tab đang
 * hover/focus (nền tối, chữ trắng) rồi trở về tab đang chọn (nền xanh lá nhạt); điện thoại thu menu vào nút ☰,
 * đóng khi chạm ra ngoài, nhấn Esc hoặc đổi trang.
 */
export function Topbar() {
  const [open, setOpen] = useState(false);
  const [scrolled, setScrolled] = useState(false);
  const [pill, setPill] = useState<Pill>({ to: null, onActive: false, left: 0, top: 0, width: 0, height: 0 });
  const { pathname } = useLocation();
  const headerRef = useRef<HTMLElement>(null);
  const navRef = useRef<HTMLElement>(null);
  const toggleRef = useRef<HTMLButtonElement>(null);

  // Đặt pill dưới một tab (hoặc tab đang chọn khi không truyền)
  const movePill = useCallback((target?: HTMLElement | null) => {
    const el = target ?? navRef.current?.querySelector<HTMLElement>(".appbar__link.active");
    if (!el) return setPill((p) => ({ ...p, to: null }));
    setPill({
      to: el.getAttribute("href"),
      onActive: el.classList.contains("active"),
      left: el.offsetLeft,
      top: el.offsetTop,
      width: el.offsetWidth,
      height: el.offsetHeight,
    });
  }, []);

  // Đổi trang: đóng menu điện thoại, pill về tab mới; đổi kích thước cửa sổ: tính lại vị trí
  useLayoutEffect(() => {
    setOpen(false);
    movePill();
    const onResize = () => movePill();
    void document.fonts?.ready.then(onResize); // font tải xong thì chữ đổi rộng, đo lại
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [pathname, movePill]);

  // Cuộn trang: thêm bóng nhẹ dưới topbar
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 4);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  // Menu điện thoại đang mở: Esc đóng và trả focus về nút ☰; chạm/bấm ngoài topbar cũng đóng
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        toggleRef.current?.focus();
      }
    };
    const onPointer = (e: PointerEvent) => {
      if (!headerRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open]);

  return (
    <header ref={headerRef} className={`appbar ${scrolled ? "appbar--scrolled" : ""}`}>
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
          onMouseLeave={() => movePill()}
          onBlur={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget)) movePill();
          }}
        >
          <span
            className={`appbar__pill ${pill.onActive ? "appbar__pill--active" : ""}`}
            aria-hidden="true"
            style={{
              width: pill.width,
              height: pill.height,
              transform: `translate(${pill.left}px, ${pill.top}px)`,
              opacity: pill.to ? 1 : 0,
            }}
          />
          {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              end={to === "/"}
              className={`appbar__link ${pill.to === to ? (pill.onActive ? "appbar__link--current" : "appbar__link--lit") : ""}`}
              onMouseEnter={(e) => movePill(e.currentTarget)}
              onFocus={(e) => movePill(e.currentTarget)}
            >
              <Icon size={18} aria-hidden="true" />
              {label}
            </NavLink>
          ))}
        </nav>

        <span className="appbar__env" title="Dữ liệu qua API dev, gồm cả thiết bị chưa duyệt">
          Môi trường dev
        </span>
      </div>
    </header>
  );
}
