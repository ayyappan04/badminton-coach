import { useEffect, useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { CoachNoteItem, Video } from "../types";

const STANCE_STYLE: Record<string, string> = {
  agree: "bg-[var(--positive-soft)] text-[var(--positive)]",
  adjust: "bg-[var(--warning-soft)] text-[var(--warning)]",
  disagree: "bg-[var(--negative-soft)] text-[var(--negative)]",
};

/** Student side of the Phase-4 coach review loop: invite a coach (by email)
 * to this specific match, and read their notes — a human layer over the AI
 * insights, anchored to the same video timestamps. */
export function CoachReviewSection({ video, onSeek }: { video: Video; onSeek: (t: number) => void }) {
  const [notes, setNotes] = useState<CoachNoteItem[]>([]);
  const [email, setEmail] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);

  useEffect(() => {
    setNotes([]);
    setStatus(null);
    api.get<CoachNoteItem[]>(`/videos/${video.id}/coach-notes`).then(setNotes).catch(() => {});
  }, [video.id]);

  async function invite(e: FormEvent) {
    e.preventDefault();
    setStatus(null);
    setInviting(true);
    try {
      await api.post(`/videos/${video.id}/coach-reviews`, { coach_email: email });
      setStatus(`Invited ${email} — they'll see this match under Community → Coaching reviews.`);
      setEmail("");
    } catch (err) {
      setStatus(err instanceof Error ? err.message : "Invite failed");
    } finally {
      setInviting(false);
    }
  }

  return (
    <div className="space-y-3">
      <form onSubmit={invite} className="flex gap-2">
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="Coach's account email…"
          required
          className="flex-1 text-sm border border-[var(--separator)] rounded-md px-3 py-2 focus:outline-none focus:border-[var(--accent)]"
        />
        <button
          type="submit"
          disabled={inviting}
          className="text-sm bg-[var(--accent)] text-white rounded-md px-4 hover:bg-[var(--accent-pressed)] disabled:opacity-50"
        >
          Invite to review
        </button>
      </form>
      {status && <p className="text-xs text-[var(--text-secondary)]">{status}</p>}
      <p className="text-[11px] text-[var(--text-secondary)]">
        Your coach sees only this match while the review is active — you can revoke access any time from Community.
      </p>

      {notes.length > 0 && (
        <div className="space-y-2">
          {notes.map((n) => (
            <div key={n.note_id} className="border border-[var(--viz-series-2)]/40 bg-[var(--viz-series-2-soft)] rounded-lg p-3">
              <div className="flex items-center gap-2 mb-1 text-xs">
                <span className="font-medium">{n.coach_name}</span>
                <button onClick={() => onSeek(n.timestamp_s)} className="text-[var(--accent)] hover:underline">
                  {formatTime(n.timestamp_s)}
                </button>
                {n.stance && (
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${STANCE_STYLE[n.stance] || ""}`}>
                    {n.stance === "agree" ? "confirms AI" : n.stance === "adjust" ? "adjusts AI" : "overrides AI"}
                  </span>
                )}
              </div>
              <p className="text-sm">{n.comment}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function formatTime(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}
