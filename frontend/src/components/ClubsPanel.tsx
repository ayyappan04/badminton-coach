import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { Club, ClubDetail } from "../types";

export function ClubsPanel() {
  const [clubs, setClubs] = useState<Club[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [detail, setDetail] = useState<ClubDetail | null>(null);

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

  async function toggleDetail(clubId: string) {
    if (expanded === clubId) {
      setExpanded(null);
      setDetail(null);
      return;
    }
    setExpanded(clubId);
    setDetail(null);
    try {
      setDetail(await api.get<ClubDetail>(`/community/clubs/${clubId}`));
    } catch {
      setExpanded(null);
    }
  }

  return (
    <div className="space-y-3">
      {clubs.length === 0 && !creating && (
        <p className="text-sm text-[var(--text-secondary)]">No clubs yet — create the first one for your group.</p>
      )}

      {clubs.map((c) => (
        <div key={c.club_id} className="border border-[var(--separator)] rounded-lg bg-[var(--surface)]">
          <div className="p-3 flex items-center justify-between gap-3">
            <button onClick={() => c.my_role && toggleDetail(c.club_id)} className="min-w-0 text-left flex-1 disabled:cursor-default" disabled={!c.my_role}>
              <p className="text-sm font-medium truncate">{c.name}</p>
              <p className="text-xs text-[var(--text-secondary)] truncate">
                {c.member_count} member{c.member_count === 1 ? "" : "s"}
                {c.description ? ` · ${c.description}` : ""}
                {c.my_role ? (expanded === c.club_id ? " · hide team view" : " · view team") : ""}
              </p>
            </button>
            {c.my_role ? (
              <span className="text-[10px] px-2 py-1 rounded-full bg-[var(--accent-soft)] text-[var(--accent)] capitalize shrink-0">{c.my_role}</span>
            ) : (
              <button onClick={() => join(c.club_id)} className="text-xs bg-[var(--accent)] text-white rounded-md px-3 py-1.5 shrink-0 hover:bg-[var(--accent-pressed)]">
                Join
              </button>
            )}
          </div>

          {expanded === c.club_id && (
            <div className="border-t border-[var(--separator)] p-3">
              {!detail ? (
                <p className="text-xs text-[var(--text-secondary)]">Loading team view…</p>
              ) : (
                <>
                  <div className="flex items-baseline justify-between mb-2">
                    <h4 className="text-xs font-semibold uppercase text-[var(--text-secondary)]">Team dashboard</h4>
                    {detail.team_dashboard.avg_development_score !== null && (
                      <span className="text-xs">
                        Team avg score: <span className="font-semibold text-[var(--accent)]">{detail.team_dashboard.avg_development_score}</span>
                      </span>
                    )}
                  </div>
                  <div className="space-y-1.5">
                    {detail.members.map((m) => (
                      <div key={m.user_id} className="flex items-center justify-between text-xs bg-[var(--surface-raised)] border border-[var(--separator)] rounded-md px-2.5 py-1.5">
                        <span className="truncate">
                          {m.display_name}
                          <span className="text-[var(--text-secondary)] capitalize"> · {m.role}</span>
                        </span>
                        {m.shares_progress ? (
                          <span className="text-[var(--text-secondary)] shrink-0">
                            score {m.development_score ?? "—"} · {m.matches_analyzed} match{m.matches_analyzed === 1 ? "" : "es"}
                            {m.top_style ? ` · ${m.top_style}` : ""}
                          </span>
                        ) : (
                          <span className="text-[var(--text-secondary)]/60 shrink-0">progress private</span>
                        )}
                      </div>
                    ))}
                  </div>
                  <p className="text-[10px] text-[var(--text-secondary)] mt-2">{detail.team_dashboard.note}</p>
                </>
              )}
            </div>
          )}
        </div>
      ))}

      {creating ? (
        <form onSubmit={createClub} className="border border-[var(--separator)] rounded-lg bg-[var(--surface)] p-3 space-y-2">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Club name"
            className="w-full text-sm border border-[var(--separator)] rounded-md px-2.5 py-1.5 focus:outline-none focus:border-[var(--accent)]"
            required
          />
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Description (optional)"
            className="w-full text-sm border border-[var(--separator)] rounded-md px-2.5 py-1.5 focus:outline-none focus:border-[var(--accent)]"
          />
          <div className="flex gap-2">
            <button type="submit" className="text-xs bg-[var(--accent)] text-white rounded-md px-3 py-1.5">Create</button>
            <button type="button" onClick={() => setCreating(false)} className="text-xs text-[var(--text-secondary)]">Cancel</button>
          </div>
        </form>
      ) : (
        <button onClick={() => setCreating(true)} className="text-xs text-[var(--accent)] hover:underline">
          + Create a club
        </button>
      )}
    </div>
  );
}
