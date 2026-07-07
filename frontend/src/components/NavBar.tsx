import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export function NavBar() {
  const { user, logout } = useAuth();
  const location = useLocation();

  const linkClass = (path: string) =>
    `px-3 py-2 rounded-md text-sm font-medium transition ${
      location.pathname === path
        ? "bg-[var(--color-accent)] text-white"
        : "text-[var(--color-ink-soft)] hover:text-[var(--color-ink)] hover:bg-white/5"
    }`;

  return (
    <nav className="border-b border-[var(--color-border)] bg-[var(--color-bg-raised)]/90 backdrop-blur sticky top-0 z-30">
      <div className="max-w-6xl mx-auto px-4 flex items-center justify-between h-14">
        <div className="flex items-center gap-6">
          <Link to="/" className="flex items-center gap-2.5 font-semibold tracking-tight text-[var(--color-ink)]">
            <ShuttleLogo />
            ShuttleSense
          </Link>
          {user && (
            <div className="flex gap-1">
              <Link to="/" className={linkClass("/")}>Coach</Link>
              <Link to="/dashboard" className={linkClass("/dashboard")}>Dashboard</Link>
              <Link to="/profile" className={linkClass("/profile")}>Profile</Link>
              <Link to="/community" className={linkClass("/community")}>Community</Link>
            </div>
          )}
        </div>
        {user && (
          <div className="flex items-center gap-3 text-sm">
            <span className="w-7 h-7 rounded-full bg-[var(--color-accent)] text-white flex items-center justify-center text-xs font-semibold">
              {user.display_name.charAt(0).toUpperCase()}
            </span>
            <span className="text-[var(--color-ink-soft)]">{user.display_name}</span>
            <button onClick={logout} className="text-[var(--color-accent)] hover:underline">
              Sign out
            </button>
          </div>
        )}
      </div>
    </nav>
  );
}

function ShuttleLogo() {
  return (
    <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
      <circle cx="12" cy="12" r="11" fill="var(--color-accent-soft)" stroke="var(--color-accent)" strokeWidth="1.5" />
      {/* shuttlecock: cork + feathers */}
      <circle cx="12" cy="16.2" r="2.4" fill="var(--color-accent)" />
      <path d="M12 14 L8.2 6.5 M12 14 L12 5.5 M12 14 L15.8 6.5" stroke="var(--color-accent)" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  );
}
