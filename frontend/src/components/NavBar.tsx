import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

/** Route → visible label. Routes are unchanged; only the wording is clearer. */
const NAV = [
  { to: "/", label: "Coach" },
  { to: "/dashboard", label: "Matches" },
  { to: "/profile", label: "Progress" },
  { to: "/community", label: "Community" },
];

export function NavBar() {
  const { user } = useAuth();
  const location = useLocation();
  const isActive = (to: string) =>
    to === "/" ? location.pathname === "/" : location.pathname.startsWith(to);

  return (
    <>
      <header
        className="sticky top-0 z-40 border-b backdrop-blur-xl"
        style={{
          height: "var(--header-height)",
          borderColor: "var(--separator)",
          background: "color-mix(in srgb, var(--background) 82%, transparent)",
        }}
      >
        <div
          className="mx-auto h-full px-4 sm:px-6 flex items-center justify-between gap-4"
          style={{ maxWidth: "var(--content-width)" }}
        >
          <div className="flex items-center gap-7 min-w-0">
            <Link
              to="/"
              className="flex items-center gap-2 shrink-0"
              style={{ color: "var(--text-primary)" }}
            >
              <Mark />
              <span className="font-semibold tracking-tight text-[15px]">ShuttleSense</span>
            </Link>

            {user && (
              <nav aria-label="Primary" className="hidden md:flex items-center gap-1">
                {NAV.map((item) => {
                  const active = isActive(item.to);
                  return (
                    <Link
                      key={item.to}
                      to={item.to}
                      aria-current={active ? "page" : undefined}
                      className="relative px-3 py-2 text-[14px] rounded-[var(--radius-sm)] transition-colors"
                      style={{
                        color: active ? "var(--text-primary)" : "var(--text-secondary)",
                        fontWeight: active ? 600 : 450,
                      }}
                    >
                      {item.label}
                      {active && (
                        <span
                          className="absolute left-3 right-3 -bottom-[9px] h-[2px] rounded-full"
                          style={{ background: "var(--accent)" }}
                          aria-hidden="true"
                        />
                      )}
                    </Link>
                  );
                })}
              </nav>
            )}
          </div>

          {user && <AccountMenu />}
        </div>
      </header>

      {user && <MobileNav isActive={isActive} />}
    </>
  );
}

function AccountMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (!open) return;
    const onPointer = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!user) return null;
  const initial = user.display_name.charAt(0).toUpperCase();

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Account menu for ${user.display_name}`}
        className="w-8 h-8 rounded-full flex items-center justify-center text-[13px] font-semibold text-white transition-transform hover:scale-105"
        style={{ background: "var(--accent)" }}
      >
        {initial}
      </button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-10 w-56 rounded-[var(--radius-lg)] border py-1.5 z-50"
          style={{
            background: "var(--surface-raised)",
            borderColor: "var(--separator-strong)",
            boxShadow: "var(--shadow-lg)",
          }}
        >
          <div className="px-3 py-2 border-b" style={{ borderColor: "var(--separator)" }}>
            <p className="text-[14px] font-medium truncate" style={{ color: "var(--text-primary)" }}>
              {user.display_name}
            </p>
            <p className="text-[12px] truncate" style={{ color: "var(--text-tertiary)" }}>
              {user.email}
            </p>
          </div>
          <MenuItem onClick={() => { setOpen(false); navigate("/profile"); }}>Your progress</MenuItem>
          <MenuItem onClick={() => { setOpen(false); navigate("/community"); }}>Privacy &amp; sharing</MenuItem>
          <div className="my-1 border-t" style={{ borderColor: "var(--separator)" }} />
          <MenuItem onClick={() => { setOpen(false); logout(); }} danger>
            Sign out
          </MenuItem>
        </div>
      )}
    </div>
  );
}

function MenuItem({ children, onClick, danger }: { children: React.ReactNode; onClick: () => void; danger?: boolean }) {
  return (
    <button
      role="menuitem"
      onClick={onClick}
      className="w-full text-left px-3 py-2 text-[14px] transition-colors hover:bg-[var(--surface-hover)]"
      style={{ color: danger ? "var(--negative)" : "var(--text-secondary)" }}
    >
      {children}
    </button>
  );
}

/** Bottom navigation on small screens — 44px+ targets, thumb-reachable. */
function MobileNav({ isActive }: { isActive: (to: string) => boolean }) {
  return (
    <nav
      aria-label="Primary"
      className="md:hidden fixed bottom-0 inset-x-0 z-40 border-t backdrop-blur-xl"
      style={{
        borderColor: "var(--separator)",
        background: "color-mix(in srgb, var(--background) 90%, transparent)",
        paddingBottom: "env(safe-area-inset-bottom)",
      }}
    >
      <div className="grid grid-cols-4">
        {NAV.map((item) => {
          const active = isActive(item.to);
          return (
            <Link
              key={item.to}
              to={item.to}
              aria-current={active ? "page" : undefined}
              className="flex flex-col items-center justify-center gap-1 h-14 text-[11px] transition-colors"
              style={{ color: active ? "var(--accent)" : "var(--text-tertiary)", fontWeight: active ? 600 : 400 }}
            >
              <NavIcon name={item.label} active={active} />
              {item.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

function NavIcon({ name, active }: { name: string; active: boolean }) {
  const stroke = active ? "var(--accent)" : "var(--text-tertiary)";
  const common = { width: 18, height: 18, fill: "none", stroke, strokeWidth: 1.6, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  if (name === "Coach") return <svg viewBox="0 0 24 24" {...common}><circle cx="12" cy="8" r="3.2" /><path d="M5.5 20a6.5 6.5 0 0 1 13 0" /></svg>;
  if (name === "Matches") return <svg viewBox="0 0 24 24" {...common}><rect x="3" y="5" width="18" height="14" rx="2.5" /><path d="M10 9.5l5 2.5-5 2.5z" /></svg>;
  if (name === "Progress") return <svg viewBox="0 0 24 24" {...common}><path d="M4 18V9M9.5 18V5M15 18v-6M20.5 18v-9" /></svg>;
  return <svg viewBox="0 0 24 24" {...common}><circle cx="9" cy="9" r="3" /><path d="M3 19a6 6 0 0 1 12 0M16 6.5a3 3 0 0 1 0 5.8M18 19a5.6 5.6 0 0 0-2-4" /></svg>;
}

function Mark() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
      <circle cx="12" cy="12" r="10.5" fill="var(--accent-soft)" stroke="var(--accent-line)" strokeWidth="1" />
      <circle cx="12" cy="16" r="2.3" fill="var(--accent)" />
      <path
        d="M12 13.8 L8.4 6.8 M12 13.8 L12 5.8 M12 13.8 L15.6 6.8"
        stroke="var(--accent)"
        strokeWidth="1.3"
        strokeLinecap="round"
      />
    </svg>
  );
}
