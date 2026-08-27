import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, isNetworkError, setSupabaseToken } from "../api/client";
import { supabase, supabaseEnabled } from "../lib/supabase";
import type { User } from "../types";

/* ==========================================================================
   Authentication.

   One provider, two backends, chosen by build configuration:

     Supabase Auth  — production. Supabase owns credentials, email
                      verification and password reset. This app never sees a
                      password, and the backend refuses its own local
                      credential endpoints when AUTH_MODE=supabase.

     Legacy JWT     — local development and the test suite, unchanged.

   The public surface is identical either way, so no screen needs to know
   which one is running.
   ========================================================================== */

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  provider: "supabase" | "legacy";
  /** Set when the API host cannot be reached at all, as opposed to reaching it
   *  and being told we are not signed in. Those look identical to a user
   *  staring at a sign-in form that silently does nothing, so the difference is
   *  surfaced rather than swallowed. */
  apiReachable: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, displayName: string) => Promise<void>;
  logout: () => Promise<void>;
  requestPasswordReset: (email: string) => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [apiReachable, setApiReachable] = useState(true);

  /** Fetch the application profile. The Supabase session establishes WHO the
   *  user is; the profile row carries what this product knows about them. */
  const loadProfile = useCallback(async () => {
    try {
      setUser(await api.get<User>("/auth/me"));
      setApiReachable(true);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        setUser(null);
        setApiReachable(true);   // the server answered; it just said no
        return;
      }
      // status 0 = no HTTP response at all: wrong VITE_API_BASE_URL, API not
      // deployed, CORS refusal, or the host is down.
      if (isNetworkError(err)) setApiReachable(false);
      // A transient failure must not look like a sign-out — the session is
      // still valid.
    }
  }, []);

  /* Probe once on load so a signed-out visitor also learns the API is down,
     instead of finding out when the sign-in button does nothing. */
  useEffect(() => {
    let cancelled = false;
    api.get("/health")
      .then(() => { if (!cancelled) setApiReachable(true); })
      .catch((err) => { if (!cancelled && isNetworkError(err)) setApiReachable(false); });
    return () => { cancelled = true; };
  }, []);

  /* --- Supabase --------------------------------------------------------- */
  useEffect(() => {
    if (!supabaseEnabled || !supabase) return;

    let active = true;
    supabase.auth.getSession().then(async ({ data }) => {
      if (!active) return;
      setSupabaseToken(data.session?.access_token ?? null);
      if (data.session) await loadProfile();
      setLoading(false);
    });

    // Fires on sign-in, sign-out and every background token refresh, so the
    // cached token used by <video> URLs never goes stale.
    const { data: sub } = supabase.auth.onAuthStateChange(async (event, session) => {
      setSupabaseToken(session?.access_token ?? null);
      if (event === "SIGNED_OUT") {
        setUser(null);
        return;
      }
      if (session && (event === "SIGNED_IN" || event === "INITIAL_SESSION")) {
        await loadProfile();
      }
    });

    return () => { active = false; sub.subscription.unsubscribe(); };
  }, [loadProfile]);

  /* --- Legacy ----------------------------------------------------------- */
  useEffect(() => {
    if (supabaseEnabled) return;
    const token = localStorage.getItem("token");
    if (!token) {
      setLoading(false);
      return;
    }
    api.get<User>("/auth/me")
      .then(setUser)
      .catch((err) => {
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          localStorage.removeItem("token");
        }
      })
      .finally(() => setLoading(false));
  }, []);

  async function login(email: string, password: string) {
    if (supabaseEnabled && supabase) {
      const { error } = await supabase.auth.signInWithPassword({ email, password });
      if (error) throw new Error(error.message);
      await loadProfile();
      return;
    }
    const res = await api.post<{ token: string; user: User }>("/auth/login", { email, password });
    localStorage.setItem("token", res.token);
    setUser(res.user);
  }

  async function register(email: string, password: string, displayName: string) {
    if (supabaseEnabled && supabase) {
      const { error } = await supabase.auth.signUp({
        email, password,
        options: {
          data: { display_name: displayName },
          emailRedirectTo: `${window.location.origin}/verify-email`,
        },
      });
      if (error) throw new Error(error.message);
      // With email confirmation on, there is no session yet. The profile row
      // is created lazily by the backend on the first authenticated request.
      await loadProfile();
      return;
    }
    const res = await api.post<{ token: string; user: User }>("/auth/register", {
      email, password, display_name: displayName,
    });
    localStorage.setItem("token", res.token);
    setUser(res.user);
  }

  async function logout() {
    if (supabaseEnabled && supabase) {
      await supabase.auth.signOut();
      setSupabaseToken(null);
      setUser(null);
      return;
    }
    try {
      await api.post("/auth/logout");
    } catch {
      // Server-side revocation is best effort; the local session ends either way.
    }
    localStorage.removeItem("token");
    setUser(null);
  }

  async function requestPasswordReset(email: string) {
    if (supabaseEnabled && supabase) {
      const { error } = await supabase.auth.resetPasswordForEmail(email, {
        redirectTo: `${window.location.origin}/reset-password`,
      });
      if (error) throw new Error(error.message);
      return;
    }
    await api.post("/auth/request-password-reset", { email });
  }

  return (
    <AuthContext.Provider
      value={{
        user, loading, apiReachable, provider: supabaseEnabled ? "supabase" : "legacy",
        login, register, logout, requestPasswordReset,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
