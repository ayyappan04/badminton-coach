import { Navigate, Route, Routes } from "react-router-dom";
import { NavBar } from "./components/NavBar";
import { Welcome } from "./pages/Welcome";
import { Dashboard } from "./pages/Dashboard";
import { Profile } from "./pages/Profile";
import { Community } from "./pages/Community";
import { ForgotPassword, ResetPassword, VerifyEmail } from "./pages/AccountFlows";
import { useAuth } from "./context/AuthContext";

function App() {
  const { user, loading } = useAuth();

  if (loading) {
    return <div className="flex items-center justify-center h-screen text-sm text-[var(--color-ink-soft)]">Loading...</div>;
  }

  return (
    <>
      <NavBar />
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
    </>
  );
}

export default App;
