import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { TrackedPerson, Video } from "../types";

export function PlayerSelectionPanel({ video, onDone }: { video: Video; onDone: () => void }) {
  const [persons, setPersons] = useState<TrackedPerson[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    api.get<TrackedPerson[]>(`/videos/${video.id}/tracked-persons`).then(setPersons).catch(() => {});
  }, [video.id]);

  async function claim(personId: string, role: string) {
    setBusy(personId);
    try {
      await api.post(`/videos/${video.id}/tracked-persons/${personId}/claim`, { role });
      onDone();
    } finally {
      setBusy(null);
    }
  }

  if (persons.length === 0) {
    return (
      <p className="text-sm text-[var(--color-ink-soft)]">
        No distinct tracked people were found yet for this video.
      </p>
    );
  }

  return (
    <div className="border border-[var(--color-warn)]/40 bg-[var(--color-warn-soft)] rounded-xl p-5">
      <h3 className="font-medium mb-1">Which one is you?</h3>
      <p className="text-sm text-[var(--color-ink-soft)] mb-4">
        The system tracked {persons.length} distinct people in this video. Confirm which one is
        you so coaching insights are generated for the right player.
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {persons.map((p) => (
          <div key={p.id} className="bg-[var(--color-card)] border border-[var(--color-border)] rounded-lg p-3 text-center">
            <div className="h-16 flex items-center justify-center">
              <div
                className="bg-[var(--color-accent-soft)] border border-[var(--color-accent)] rounded"
                style={{
                  width: Math.max(20, Math.min(60, (p.sample_box?.w ?? 40) / 3)),
                  height: Math.max(30, Math.min(64, (p.sample_box?.h ?? 90) / 2)),
                }}
              />
            </div>
            <p className="text-xs text-[var(--color-ink-soft)] mb-2">
              Tracked player #{p.track_id} · {Math.round(p.track_confidence * 100)}% confidence
            </p>
            <button
              disabled={busy === p.id}
              onClick={() => claim(p.id, "self")}
              className="w-full text-xs bg-[var(--color-accent)] text-white rounded-md py-1.5 font-medium disabled:opacity-50 hover:bg-[var(--color-accent-dark)]"
            >
              {busy === p.id ? "Confirming..." : "This is me"}
            </button>
            <button
              disabled={busy === p.id}
              onClick={() => claim(p.id, "partner")}
              className="w-full text-xs mt-1 border border-[var(--color-border-strong)] text-[var(--color-ink-soft)] rounded-md py-1.5 hover:bg-white/5"
            >
              This is my partner
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
