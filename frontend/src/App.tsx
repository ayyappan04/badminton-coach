import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { NavBar } from "./components/NavBar";
import { Welcome } from "./pages/Welcome";
import { ForgotPassword, ResetPassword, VerifyEmail } from "./pages/AccountFlows";
import { useAuth } from "./context/AuthContext";

/* --- route-level code splitting --------------------------------------------
   Welcome is eager: it is the first paint for every signed-out visitor and the
   only route most first-time visitors ever see.

   The three authenticated routes are lazy. They pull in Recharts and the whole
   analysis surface, which together were roughly two thirds of a single 926 KB
   bundle that every visitor downloaded before seeing a landing page. Nobody
   needs the radar chart before they have signed in.
   -------------------------------------------------------------------------- */
const Dashboard = lazy(() => import("./pages/Dashboard").then((m) => ({ default: m.Dashboard })));
const Profile = lazy(() => import("./pages/Profile").then((m) => ({ default: m.Profile })));
const Community = lazy(() => import("./pages/Community").then((m) => ({ default: m.Community })));

function App() {
  const { user, loading, apiReachable } = useAuth();

  if (loading) {
    return <div className="flex items-center justify-center h-screen text-sm text-[var(--text-secondary)]">Loading...</div>;
  }

  return (
    <>
      {!apiReachable && <ApiUnreachableBanner />}
      <NavBar />
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/" element={<Welcome />} />
          {/* Public account flows — reachable while signed out, by design. */}
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword />} />
          <Route path="/verify-email" element={<VerifyEmail />} />
          <Route path="/dashboard" element={user ? <Dashboard /> : <Navigate to="/" replace />} />
          <Route path="/profile" element={user ? <Profile /> : <Navigate to="/" replace />} />
          <Route path="/community" element={user ? <Community /> : <Navigate to="/" replace />} />
            <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </>
  );
}

/** Held while a lazy route chunk loads. Deliberately minimal — a skeleton of a
 *  page the user has not navigated to yet is noise, and on a fast connection
 *  this is visible for a single frame. */
function RouteFallback() {
  return (
    <div
      className="flex items-center justify-center py-24 text-[13px]"
      style={{ color: "var(--text-tertiary)" }}
    >
      Loading…
    </div>
  );
}

/** Shown when the API host cannot be reached at all.
 *
 *  The frontend deploys independently of the API container, so this is a real
 *  and recoverable state — not an error to hide. Saying so plainly is better
 *  than a sign-in form that appears to work and then does nothing. */
function ApiUnreachableBanner() {
  return (
    <div
      role="status"
      className="px-4 py-2.5 text-[13px] text-center"
      style={{
        background: "var(--warning-soft)",
        color: "var(--warning)",
        borderBottom: "1px solid var(--separator)",
      }}
    >
      Can't reach the ShuttleSense API. Sign-in, uploads and analysis are
      unavailable until the API service is running.
    </div>
  );
}

export default App;
