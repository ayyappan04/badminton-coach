import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { CoachingInsight, Video } from "../types";

const CATEGORY_COLOR: Record<string, string> = {
  technique: "bg-[var(--color-accent-soft)] text-[var(--color-accent)]",
  footwork: "bg-purple-500/15 text-purple-300",
  positioning: "bg-[var(--color-court-soft)] text-[var(--color-court)]",
  tactics: "bg-[var(--color-warn-soft)] text-[var(--color-warn)]",
  stamina: "bg-pink-500/15 text-pink-300",
};

function guessTechniqueReference(insight: CoachingInsight): string | null {
  const text = insight.observed_action.toLowerCase();
  if (text.includes("smash")) return "smash";
  if (text.includes("clear")) return "overhead_clear";
  if (text.includes("lunge")) return "net_lunge";
  if (text.includes("split step")) return "split_step";
  if (insight.category === "footwork") return "split_step";
  if (insight.category === "technique") return "overhead_clear";
  return null;
}

export function InsightsPanel({
  video,
  onSeek,
  onOpenTechnique,
}: {
  video: Video;
  onSeek: (t: number) => void;
  onOpenTechnique: (name: string, timestamp: number) => void;
}) {
  const [insights, setInsights] = useState<CoachingInsight[]>([]);
  const [sharedIndex, setSharedIndex] = useState<number | null>(null);

  useEffect(() => {
    api.get<CoachingInsight[]>(`/videos/${video.id}/insights`).then(setInsights).catch(() => {});
  }, [video.id]);

  async function shareClip(insight: CoachingInsight, index: number) {
    // Uses the account's default clip-sharing scope (set in Community → Privacy).
    let scope = "private";
    try {
      const consent = await api.get<{ default_clip_share_scope: string }>("/consent-settings");
      scope = consent.default_clip_share_scope;
    } catch { /* keep private on failure */ }
    await api.post(`/videos/${video.id}/clips`, {
      video_id: video.id,
      clip_start_s: Math.max(0, insight.timestamp_s - 4),
      clip_end_s: insight.timestamp_s + 4,
      visibility: scope,
      caption: `${insight.category}: ${insight.correction.slice(0, 80)}`,
    });
    setSharedIndex(index);
    setTimeout(() => setSharedIndex(null), 2500);
  }

  if (insights.length === 0) {
    return (
      <p className="text-sm text-[var(--color-ink-soft)]">
        No coaching insights yet. If this video needs you to confirm which tracked player is you,
        do that first — insights generate right after.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {insights.map((insight, i) => {
        const techRef = guessTechniqueReference(insight);
        return (
          <div key={i} className="border border-[var(--color-border)] rounded-lg p-4 bg-[var(--color-card)]">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className={`text-[10px] px-2 py-0.5 rounded-full font-medium ${CATEGORY_COLOR[insight.category] || "bg-white/10"}`}>
                  {insight.category}
                </span>
                <button onClick={() => onSeek(insight.timestamp_s)} className="text-xs text-[var(--color-accent)] hover:underline">
                  {formatTime(insight.timestamp_s)}
                </button>
              </div>
              <ConfidenceBadge value={insight.confidence} />
            </div>
            <p className="text-sm mb-1.5"><span className="font-medium">Observed:</span> {insight.observed_action}</p>
            <p className="text-sm mb-1.5 text-[var(--color-ink-soft)]"><span className="font-medium text-[var(--color-ink)]">Impact:</span> {insight.likely_impact}</p>
            <p className="text-sm mb-2"><span className="font-medium">Try this:</span> {insight.correction}</p>
            {insight.limitations.length > 0 && (
              <p className="text-xs text-[var(--color-ink-soft)] mb-2">
                Limitations: {insight.limitations.join(", ").replace(/_/g, " ")}
              </p>
            )}
            <div className="flex gap-2 items-center flex-wrap">
              {techRef && (
                <button
                  onClick={() => onOpenTechnique(techRef, insight.timestamp_s)}
                  className="text-xs border border-[var(--color-accent)] text-[var(--color-accent)] rounded-md px-3 py-1.5 font-medium hover:bg-[var(--color-accent-soft)]"
                >
                  Open Comparison Studio
                </button>
              )}
              <button
                onClick={() => shareClip(insight, i)}
                className="text-xs border border-[var(--color-border-strong)] text-[var(--color-ink-soft)] rounded-md px-3 py-1.5 hover:bg-white/5"
              >
                {sharedIndex === i ? "Clip saved ✓" : "Share clip"}
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function ConfidenceBadge({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const color =
    pct >= 70 ? "text-[var(--color-good)]" : pct >= 45 ? "text-[var(--color-warn)]" : "text-[var(--color-bad)]";
  return <span className={`text-xs ${color}`}>{pct}% confidence</span>;
}

function formatTime(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}
