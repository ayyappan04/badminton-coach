import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { TechniqueScoreEntry, Video } from "../types";

const LABELS: Record<string, string> = {
  footwork: "Footwork",
  balance: "Balance",
  stability: "Stability",
  racket_preparation: "Racket preparation",
  contact_height: "Contact height",
  shot_timing: "Shot timing",
  recovery_speed: "Recovery speed",
  movement_efficiency: "Movement efficiency",
  body_alignment: "Body alignment",
  execution_consistency: "Consistency",
};

export function Scorecards({ video }: { video: Video }) {
  const [cards, setCards] = useState<Record<string, TechniqueScoreEntry> | null>(null);
  const [showBasis, setShowBasis] = useState(false);

  useEffect(() => {
    setCards(null);
    api.get<Record<string, TechniqueScoreEntry>>(`/videos/${video.id}/scorecards`).then(setCards).catch(() => setCards(null));
  }, [video.id]);

  if (!cards) {
    return <p className="text-sm text-[var(--color-ink-soft)]">Scorecards aren't available yet for this video.</p>;
  }

  const keys = Object.keys(LABELS).filter((k) => k in cards);

  return (
    <div>
      <div className="flex justify-end mb-2">
        <button onClick={() => setShowBasis((v) => !v)} className="text-xs text-[var(--color-accent)] hover:underline">
          {showBasis ? "Hide measurement basis" : "How is this measured?"}
        </button>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
        {keys.map((key) => {
          const entry = cards[key];
          const score = entry?.score;
          return (
            <div key={key} className="border border-[var(--color-border)] rounded-lg p-3 bg-[var(--color-card)]">
              <div className="flex justify-between items-baseline mb-1 gap-2">
                <span className="text-xs font-medium text-[var(--color-ink-soft)]">{LABELS[key]}</span>
                <span className="text-[10px] text-[var(--color-ink-soft)] whitespace-nowrap">{Math.round((entry?.confidence || 0) * 100)}% conf.</span>
              </div>
              <div className="h-2 bg-white/10 rounded-full overflow-hidden mb-1">
                <div className="h-full bg-[var(--color-accent)]" style={{ width: `${score ?? 0}%` }} />
              </div>
              <span className="text-lg font-semibold">{score !== null && score !== undefined ? Math.round(score) : "—"}</span>
              {showBasis && <p className="text-[10px] text-[var(--color-ink-soft)] mt-1.5">{entry.basis}</p>}
            </div>
          );
        })}
      </div>
      <p className="text-[10px] text-[var(--color-ink-soft)] mt-2">
        Video-based estimates from a single camera — read directions and repeat patterns, not exact values.
      </p>
    </div>
  );
}
