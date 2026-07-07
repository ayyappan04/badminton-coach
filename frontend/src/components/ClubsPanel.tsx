import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Club } from "../types";

export function ClubsPanel() {
  const [clubs, setClubs] = useState<Club[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);

  function refresh() {
    api.get<Club[]>("/community/clubs").then(setClubs).catch(() => {});
  }

  useEffect(refresh, []);

  async function createClub(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    await api.post("/community/clubs", { name, description: description || null });
    setName("");
    setDescription("");
    setCreating(false);
    refresh();
  }

  async function join(clubId: string) {
    await api.post(`/community/clubs/${clubId}/join`, {});
    refresh();
  }

  return (
    <div className="space-y-3">
      {clubs.length === 0 && !creating && (
        <p className="text-sm text-[var(--color-ink-soft)]">No clubs yet — create the first one for your group.</p>
      )}

      {clubs.map((c) => (
        <div key={c.club_id} className="border border-[var(--color-border)] rounded-lg bg-[var(--color-card)] p-3 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <p className="text-sm font-medium truncate">{c.name}</p>
            <p className="text-xs text-[var(--color-ink-soft)] truncate">
              {c.member_count} member{c.member_count === 1 ? "" : "s"}
              {c.description ? ` · ${c.description}` : ""}
            </p>
          </div>
          {c.my_role ? (
            <span className="text-[10px] px-2 py-1 rounded-full bg-[var(--color-accent-soft)] text-[var(--color-accent)] capitalize shrink-0">{c.my_role}</span>
          ) : (
            <button onClick={() => join(c.club_id)} className="text-xs bg-[var(--color-accent)] text-white rounded-md px-3 py-1.5 shrink-0 hover:bg-[var(--color-accent-dark)]">
              Join
            </button>
          )}
        </div>
      ))}

      {creating ? (
        <form onSubmit={createClub} className="border border-[var(--color-border)] rounded-lg bg-[var(--color-card)] p-3 space-y-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Club name"
            className="w-full text-sm border border-[var(--color-border)] rounded-md px-2.5 py-1.5 focus:outline-none focus:border-[var(--color-accent)]"
            required
          />
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Description (optional)"
            className="w-full text-sm border border-[var(--color-border)] rounded-md px-2.5 py-1.5 focus:outline-none focus:border-[var(--color-accent)]"
          />
          <div className="flex gap-2">
            <button type="submit" className="text-xs bg-[var(--color-accent)] text-white rounded-md px-3 py-1.5">Create</button>
            <button type="button" onClick={() => setCreating(false)} className="text-xs text-[var(--color-ink-soft)]">Cancel</button>
          </div>
        </form>
      ) : (
        <button onClick={() => setCreating(true)} className="text-xs text-[var(--color-accent)] hover:underline">
          + Create a club
        </button>
      )}
    </div>
  );
}
