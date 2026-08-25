import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { Button, SegmentedControl, Surface } from "../ui";

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
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Surface raised>
      <div className="mb-4">
        <SegmentedControl
          ariaLabel="Account mode"
          value={mode}
          onChange={setMode}
          options={[
            { value: "register", label: "Create account" },
            { value: "login", label: "Sign in" },
          ]}
        />
      </div>

      <form onSubmit={onSubmit} className="flex flex-col gap-3.5">
        {mode === "register" && (
          <Field label="Name">
            <input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              required
              autoComplete="name"
            />
          </Field>
        )}

        <Field label="Email">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
          />
        </Field>

        <Field
          label="Password"
          hint={
            mode === "register"
              ? "At least 10 characters, using three of: lowercase, uppercase, digits, symbols."
              : undefined
          }
        >
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={mode === "register" ? 10 : undefined}
            autoComplete={mode === "register" ? "new-password" : "current-password"}
          />
        </Field>

        {error && (
          <p role="alert" className="text-[13px]" style={{ color: "var(--negative)" }}>
            {error}
          </p>
        )}

        <Button type="submit" variant="primary" disabled={busy} fullWidth className="mt-1">
          {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
        </Button>

        {mode === "login" && (
          <Link to="/forgot-password" className="text-[13px] text-center" style={{ color: "var(--accent)" }}>
            Forgot your password?
          </Link>
        )}
      </form>
    </Surface>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[13px] font-medium" style={{ color: "var(--text-secondary)" }}>
        {label}
      </span>
      <div className="mt-1.5 [&>input]:w-full">{children}</div>
      {hint && (
        <span className="block text-[11.5px] mt-1 leading-snug" style={{ color: "var(--text-tertiary)" }}>
          {hint}
        </span>
      )}
    </label>
  );
}
