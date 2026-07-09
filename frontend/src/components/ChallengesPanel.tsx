import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { ChallengeItem, FriendItem } from "../types";

const STATUS_STYLE: Record<string, string> = {
  pending: "bg-[var(--color-warn-soft)] text-[var(--color-warn)]",
  accepted: "bg-[var(--color-accent-soft)] text-[var(--color-accent)]",
  completed: "bg-[var(--color-good-soft)] text-[var(--color-good)]",
};

export function ChallengesPanel() {
  const [challenges, setChallenges] = useState<ChallengeItem[]>([]);
  const [friends, setFriends] = useState<FriendItem[]>([]);
  const [opponentId, setOpponentId] = useState("");
  const [description, setDescription] = useState("");
  const [resultDraft, setResultDraft] = useState<Record<string, string>>({});

  function refresh() {
    api.get<ChallengeItem[]>("/challenges").then(setChallenges).catch(() => {});
  }

  useEffect(() => {
    refresh();
    api.get<FriendItem[]>("/friends").then((f) => setFriends(f.filter((x) => x.status === "accepted"))).catch(() => {});
  }, []);

  async function create(e: FormEvent) {
    e.preventDefault();
    if (!opponentId) return;
    await api.post("/challenges", { opponent_user_id: opponentId, description: description || null });
    setOpponentId("");
    setDescription("");
    refresh();
  }

  async function accept(id: string) {
    await api.post(`/challenges/${id}/accept`, {});
    refresh();
  }

  async function complete(id: string) {
    const result = resultDraft[id];
    if (!result?.trim()) return;
    await api.post(`/challenges/${id}/complete`, { result });
    refresh();
  }

  return (
    <div className="space-y-3">
      {friends.length > 0 ? (
        <form onSubmit={create} className="flex gap-2 flex-wrap">
          <select
            value={opponentId}
            onChange={(e) => setOpponentId(e.target.value)}
            className="text-xs border border-[var(--color-border)] rounded-md px-2 py-1.5"
            required
          >
            <option value="">Challenge a friend…</option>
            {friends.map((f) => <option key={f.user_id} value={f.user_id}>{f.display_name}</option>)}
          </select>
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="e.g. Best of 3, Saturday"
            className="flex-1 min-w-32 text-xs border border-[var(--color-border)] rounded-md px-2 py-1.5"
          />
          <button type="submit" className="text-xs bg-[var(--color-accent)] text-white rounded-md px-3 py-1.5 hover:bg-[var(--color-accent-dark)]">
            Send
          </button>
        </form>
      ) : (
        <p className="text-xs text-[var(--color-ink-soft)]">Add friends to start friendly challenges.</p>
      )}

      {challenges.map((c) => (
        <div key={c.challenge_id} className="border border-[var(--color-border)] rounded-lg bg-[var(--color-card)] p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="text-sm truncate">
                {c.challenger_name} → {c.opponent_name}
                {c.description ? <span className="text-[var(--color-ink-soft)]"> · {c.description}</span> : ""}
              </p>
              {c.result && <p className="text-xs text-[var(--color-good)] mt-0.5">{c.result}</p>}
            </div>
            <span className={`text-[10px] px-2 py-0.5 rounded-full shrink-0 ${STATUS_STYLE[c.status] || "bg-white/10"}`}>{c.status}</span>
          </div>
          {c.status === "pending" && c.i_am_opponent && (
            <button onClick={() => accept(c.challenge_id)} className="mt-2 text-xs bg-[var(--color-accent)] text-white rounded-md px-3 py-1.5 hover:bg-[var(--color-accent-dark)]">
              Accept challenge
            </button>
          )}
          {c.status === "accepted" && (
            <div className="mt-2 flex gap-2">
              <input
                value={resultDraft[c.challenge_id] ?? ""}
                onChange={(e) => setResultDraft((d) => ({ ...d, [c.challenge_id]: e.target.value }))}
                placeholder="Result, e.g. Arun won 21-18"
                className="flex-1 text-xs border border-[var(--color-border)] rounded-md px-2 py-1.5"
              />
              <button onClick={() => complete(c.challenge_id)} className="text-xs border border-[var(--color-good)]/50 text-[var(--color-good)] rounded-md px-3 py-1.5 hover:bg-[var(--color-good-soft)]">
                Record result
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
