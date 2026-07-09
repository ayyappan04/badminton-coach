import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { ApiKeyItem } from "../types";

/** Phase 4 integration keys: read-only, scoped, revocable. The plaintext key
 * is shown exactly once after creation. */
export function ApiKeysPanel() {
  const [keys, setKeys] = useState<ApiKeyItem[]>([]);
  const [name, setName] = useState("");
  const [freshKey, setFreshKey] = useState<string | null>(null);

  function refresh() {
    api.get<ApiKeyItem[]>("/integration/keys").then(setKeys).catch(() => {});
  }

  useEffect(refresh, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    const res = await api.post<{ api_key: string }>("/integration/keys", { name });
    setFreshKey(res.api_key);
    setName("");
    refresh();
  }

  async function revoke(id: string) {
    await api.post(`/integration/keys/${id}/revoke`, {});
    refresh();
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-[var(--color-ink-soft)]">
        Give a club or coaching tool read-only access to your profile summary and match stats. Keys never expose your
        videos or frame-level data, and you can revoke them at any time.
      </p>

      <form onSubmit={create} className="flex gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Key name, e.g. Club league tool"
          className="flex-1 text-xs border border-[var(--color-border)] rounded-md px-2.5 py-1.5 focus:outline-none focus:border-[var(--color-accent)]"
          required
        />
        <button type="submit" className="text-xs bg-[var(--color-accent)] text-white rounded-md px-3 py-1.5 hover:bg-[var(--color-accent-dark)]">
          Create key
        </button>
      </form>

      {freshKey && (
        <div className="border border-[var(--color-warn)]/40 bg-[var(--color-warn-soft)] rounded-lg p-3">
          <p className="text-xs mb-1 font-medium">Copy this key now — it won't be shown again:</p>
          <code className="text-xs break-all select-all">{freshKey}</code>
          <p className="text-[10px] text-[var(--color-ink-soft)] mt-1.5">
            Use it as an <code>X-API-Key</code> header on <code>/api/v1/integration/v1/profile</code> and <code>/matches</code>.
          </p>
        </div>
      )}

      {keys.map((k) => (
        <div key={k.key_id} className="border border-[var(--color-border)] rounded-lg bg-[var(--color-card)] p-3 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm truncate">{k.name} <code className="text-xs text-[var(--color-ink-soft)]">{k.key_prefix}…</code></p>
            <p className="text-xs text-[var(--color-ink-soft)]">
              {k.scopes}{k.revoked ? " · revoked" : k.last_used_at ? ` · last used ${k.last_used_at.slice(0, 10)}` : " · never used"}
            </p>
          </div>
          {!k.revoked && (
            <button onClick={() => revoke(k.key_id)} className="text-xs border border-[var(--color-bad)]/50 text-[var(--color-bad)] rounded-md px-3 py-1.5 shrink-0 hover:bg-[var(--color-bad-soft)]">
              Revoke
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
