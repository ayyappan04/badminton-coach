import { useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../api/client";

const CARD =
  "max-w-sm mx-auto mt-16 bg-[var(--surface)] border border-[var(--separator)] rounded-xl p-6 shadow-lg shadow-black/20 text-center";
const INPUT =
  "mt-1 w-full border border-[var(--separator)] rounded-md px-3 py-2 focus:outline-none focus:border-[var(--accent)]";
const BUTTON =
  "mt-3 w-full bg-[var(--accent)] text-white rounded-md py-2 font-medium hover:bg-[var(--accent-pressed)] disabled:opacity-50";


/** Request a reset link. The response is intentionally identical whether or
 * not the address has an account, so this screen never confirms membership. */
export function ForgotPassword() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/request-password-reset", { email });
      setSent(true);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 429
        ? "Too many requests. Please wait a few minutes and try again."
        : "Could not send the reset email. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <div className={CARD}>
        <h1 className="text-lg font-semibold mb-2">Check your inbox</h1>
        <p className="text-sm text-[var(--text-secondary)]">
          If an account exists for that address, a password reset link is on its way.
          The link expires in 30 minutes and can only be used once.
        </p>
        <Link to="/" className="inline-block mt-4 text-sm text-[var(--accent)] hover:underline">
          Back to sign in
        </Link>
      </div>
    );
  }

  return (
    <div className={CARD}>
      <h1 className="text-lg font-semibold mb-1">Reset your password</h1>
      <p className="text-sm text-[var(--text-secondary)] mb-4">
        We'll email you a link to choose a new one.
      </p>
      <form onSubmit={onSubmit} className="text-left">
        <label className="text-sm text-[var(--text-secondary)]">
          Email
          <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} className={INPUT} />
        </label>
        {error && <p className="text-sm text-[var(--negative)] mt-2">{error}</p>}
        <button type="submit" disabled={busy} className={BUTTON}>
          {busy ? "Sending..." : "Send reset link"}
        </button>
      </form>
      <Link to="/" className="inline-block mt-4 text-sm text-[var(--accent)] hover:underline">
        Back to sign in
      </Link>
    </div>
  );
}


/** Consume a reset token and set a new password. */
export function ResetPassword() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirm) {
      setError("The two passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await api.post("/auth/reset-password", { token, new_password: password });
      setDone(true);
      setTimeout(() => navigate("/"), 2500);
    } catch (err) {
      // The API's message is safe to show: it never says whether the account exists.
      setError(err instanceof Error ? err.message : "Could not reset your password.");
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <div className={CARD}>
        <h1 className="text-lg font-semibold mb-2">Link incomplete</h1>
        <p className="text-sm text-[var(--text-secondary)]">
          This reset link is missing its token. Request a new one.
        </p>
        <Link to="/forgot-password" className="inline-block mt-4 text-sm text-[var(--accent)] hover:underline">
          Request a new link
        </Link>
      </div>
    );
  }

  if (done) {
    return (
      <div className={CARD}>
        <h1 className="text-lg font-semibold mb-2 text-[var(--positive)]">Password updated</h1>
        <p className="text-sm text-[var(--text-secondary)]">
          All other sessions have been signed out. Taking you to sign in…
        </p>
      </div>
    );
  }

  return (
    <div className={CARD}>
      <h1 className="text-lg font-semibold mb-1">Choose a new password</h1>
      <p className="text-xs text-[var(--text-secondary)] mb-4">
        At least 10 characters, using three of: lowercase, uppercase, digits, symbols.
      </p>
      <form onSubmit={onSubmit} className="text-left">
        <label className="text-sm text-[var(--text-secondary)]">
          New password
          <input type="password" required minLength={10} value={password}
                 onChange={(e) => setPassword(e.target.value)} className={INPUT} />
        </label>
        <label className="text-sm text-[var(--text-secondary)] block mt-3">
          Confirm password
          <input type="password" required minLength={10} value={confirm}
                 onChange={(e) => setConfirm(e.target.value)} className={INPUT} />
        </label>
        {error && <p className="text-sm text-[var(--negative)] mt-2">{error}</p>}
        <button type="submit" disabled={busy} className={BUTTON}>
          {busy ? "Updating..." : "Update password"}
        </button>
      </form>
    </div>
  );
}


/** Consume an email-verification token. */
export function VerifyEmail() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [state, setState] = useState<"working" | "ok" | "error">("working");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!token) {
      setState("error");
      setMessage("This verification link is missing its token.");
      return;
    }
    let cancelled = false;
    api
      .post<{ verified: boolean; token?: string }>("/auth/verify-email", { token })
      .then((res) => {
        if (cancelled) return;
        // The endpoint returns a session token so the user lands signed in.
        if (res.token) localStorage.setItem("token", res.token);
        setState("ok");
      })
      .catch((err) => {
        if (cancelled) return;
        setState("error");
        setMessage(err instanceof Error ? err.message : "Verification failed.");
      });
    return () => { cancelled = true; };
  }, [token]);

  if (state === "working") {
    return <div className={CARD}><p className="text-sm text-[var(--text-secondary)]">Verifying your email…</p></div>;
  }
  if (state === "ok") {
    return (
      <div className={CARD}>
        <h1 className="text-lg font-semibold mb-2 text-[var(--positive)]">Email verified</h1>
        <p className="text-sm text-[var(--text-secondary)]">Your account is ready.</p>
        <a href="/" className="inline-block mt-4 text-sm text-[var(--accent)] hover:underline">
          Go to your coach
        </a>
      </div>
    );
  }
  return (
    <div className={CARD}>
      <h1 className="text-lg font-semibold mb-2">Verification failed</h1>
      <p className="text-sm text-[var(--text-secondary)]">{message}</p>
      <p className="text-xs text-[var(--text-secondary)] mt-2">
        Verification links expire and can only be used once. Sign in to request a new one.
      </p>
      <Link to="/" className="inline-block mt-4 text-sm text-[var(--accent)] hover:underline">
        Back to sign in
      </Link>
    </div>
  );
}
