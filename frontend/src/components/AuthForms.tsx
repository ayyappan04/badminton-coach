import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export function AuthForms() {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("register");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, displayName);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  const inputClass =
    "mt-1 w-full border border-[var(--color-border)] rounded-md px-3 py-2 focus:outline-none focus:border-[var(--color-accent)]";

  return (
    <div className="max-w-sm mx-auto bg-[var(--color-card)] border border-[var(--color-border)] rounded-xl p-6 shadow-lg shadow-black/20">
      <div className="flex gap-2 mb-4">
        <button
          className={`flex-1 py-1.5 rounded-md text-sm font-medium transition ${mode === "register" ? "bg-[var(--color-accent)] text-white" : "bg-white/5 text-[var(--color-ink-soft)] hover:bg-white/10"}`}
          onClick={() => setMode("register")}
        >
          Create account
        </button>
        <button
          className={`flex-1 py-1.5 rounded-md text-sm font-medium transition ${mode === "login" ? "bg-[var(--color-accent)] text-white" : "bg-white/5 text-[var(--color-ink-soft)] hover:bg-white/10"}`}
          onClick={() => setMode("login")}
        >
          Sign in
        </button>
      </div>
      <form onSubmit={onSubmit} className="flex flex-col gap-3 text-left">
        {mode === "register" && (
          <label className="text-sm text-[var(--color-ink-soft)]">
            Name
            <input
              className={inputClass}
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              required
            />
          </label>
        )}
        <label className="text-sm text-[var(--color-ink-soft)]">
          Email
          <input
            type="email"
            className={inputClass}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        <label className="text-sm text-[var(--color-ink-soft)]">
          Password
          <input
            type="password"
            className={inputClass}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={10}
          />
        </label>
        {error && <p className="text-sm text-[var(--color-bad)]">{error}</p>}
        {mode === "register" && (
          <p className="text-xs text-[var(--color-ink-soft)] -mt-1">
            At least 10 characters, using three of: lowercase, uppercase, digits, symbols.
          </p>
        )}
        <button
          type="submit"
          disabled={busy}
          className="mt-1 bg-[var(--color-accent)] text-white rounded-md py-2 font-medium hover:bg-[var(--color-accent-dark)] disabled:opacity-50"
        >
          {busy ? "Please wait..." : mode === "login" ? "Sign in" : "Create account"}
        </button>
        {mode === "login" && (
          <Link to="/forgot-password" className="text-xs text-[var(--color-accent)] hover:underline text-center">
            Forgot your password?
          </Link>
        )}
      </form>
    </div>
  );
}
