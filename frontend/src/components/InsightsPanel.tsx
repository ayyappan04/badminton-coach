import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { CoachingInsight, Video } from "../types";
import { Confidence, EmptyState, SkeletonRows, formatTimestamp, limitationLabel } from "../ui";

/** Category → accent used for the small label. Semantic colours are reserved
 *  for improvement/regression, so categories use neutral text weight instead
 *  of a rainbow of pills. */
const CATEGORY_LABEL: Record<string, string> = {
  technique: "Technique",
  footwork: "Footwork",
  positioning: "Positioning",
  tactics: "Tactics",
  stamina: "Stamina",
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
  const [insights, setInsights] = useState<CoachingInsight[] | null>(null);
  const [sharedIndex, setSharedIndex] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    setInsights(null);
    api
      .get<CoachingInsight[]>(`/videos/${video.id}/insights`)
      .then((d) => !cancelled && setInsights(d))
      .catch(() => !cancelled && setInsights([]));
    return () => {
      cancelled = true;
    };
  }, [video.id]);

  async function shareClip(insight: CoachingInsight, index: number) {
    // Uses the account's default clip-sharing scope (Community → Privacy).
    let scope = "private";
    try {
      const consent = await api.get<{ default_clip_share_scope: string }>("/consent-settings");
      scope = consent.default_clip_share_scope;
    } catch {
      /* keep private on failure */
    }
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

  if (insights === null) return <SkeletonRows rows={5} />;

  if (!insights.length) {
    return (
      <EmptyState
        compact
        title="No coaching insights yet"
        description={
          video.status === "needs_player_selection"
            ? "Confirm which tracked player is you — insights generate right after."
            : "This match didn't produce enough clean tracking to draw findings from."
        }
      />
    );
  }

  return (
    <ol className="divide-y" style={{ borderColor: "var(--separator)" }}>
      {insights.map((insight, i) => {
        const techRef = guessTechniqueReference(insight);
        return (
          <li key={i} className="py-4 first:pt-0 last:pb-0">
            <div className="flex items-baseline justify-between gap-3 mb-2">
              <span
                className="text-[11px] font-medium uppercase tracking-wider"
                style={{ color: "var(--text-tertiary)" }}
              >
                {CATEGORY_LABEL[insight.category] ?? insight.category}
              </span>
              <Confidence value={insight.confidence} showLabel />
            </div>

            <p className="text-[14px] leading-snug" style={{ color: "var(--text-primary)" }}>
              {insight.observed_action}
            </p>

            <div className="mt-2.5 space-y-1.5">
              <Line label="Why it matters">{insight.likely_impact}</Line>
              <Line label="Do this">{insight.correction}</Line>
            </div>

            {/* Evidence is a first-class control, not a footnote. */}
            <div className="mt-3 flex items-center gap-2 flex-wrap">
              <span className="text-[11px] uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
                Evidence
              </span>
              <button
                onClick={() => onSeek(insight.timestamp_s)}
                className="tnum h-7 px-2.5 rounded-[var(--radius-sm)] text-[12px] font-medium transition-colors hover:brightness-125"
                style={{ background: "var(--accent-soft)", color: "var(--accent)" }}
              >
                ▶ {formatTimestamp(insight.timestamp_s)}
              </button>

              {techRef && (
                <button
                  onClick={() => onOpenTechnique(techRef, insight.timestamp_s)}
                  className="h-7 px-2.5 rounded-[var(--radius-sm)] text-[12px] transition-colors hover:bg-[var(--surface-hover)]"
                  style={{ color: "var(--text-secondary)", border: "1px solid var(--separator-strong)" }}
                >
                  Compare technique
                </button>
              )}
              <button
                onClick={() => shareClip(insight, i)}
                className="h-7 px-2.5 rounded-[var(--radius-sm)] text-[12px] transition-colors hover:bg-[var(--surface-hover)]"
                style={{ color: "var(--text-secondary)", border: "1px solid var(--separator-strong)" }}
              >
                {sharedIndex === i ? "Clip saved" : "Share clip"}
              </button>
            </div>

            {insight.limitations.length > 0 && (
              <p className="mt-2 text-[11.5px]" style={{ color: "var(--text-tertiary)" }}>
                {insight.limitations.map(limitationLabel).join(" · ")}
              </p>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function Line({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <p className="text-[13.5px] leading-snug" style={{ color: "var(--text-secondary)" }}>
      <span style={{ color: "var(--text-tertiary)" }}>{label}: </span>
      {children}
    </p>
  );
}
