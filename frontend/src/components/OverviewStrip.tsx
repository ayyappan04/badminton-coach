import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { PlayerProfile, Video } from "../types";

interface HistorySnapshot {
  snapshot_at: string;
  radar_scores: Record<string, { score: number | null; confidence: number }>;
}

function avgScore(scores: Record<string, { score: number | null }>): number | null {
  const vals = Object.values(scores).map((v) => v.score).filter((s): s is number => s !== null);
  if (!vals.length) return null;
  return Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 10) / 10;
}

export function OverviewStrip({ profile, latestVideo }: { profile: PlayerProfile; latestVideo: Video | null }) {
  const [history, setHistory] = useState<HistorySnapshot[]>([]);
  const [drillName, setDrillName] = useState<string | null>(null);

  useEffect(() => {
    api.get<HistorySnapshot[]>("/profile/history").then(setHistory).catch(() => {});
  }, [profile.matches_analyzed_count]);

  useEffect(() => {
    const tags = profile.training_plan?.recommended_drill_tags;
    if (tags && tags.length > 0) {
      api.get<{ name: string }[]>(`/drills?tag=${tags[0]}`).then((d) => setDrillName(d[0]?.name ?? null)).catch(() => {});
    }
  }, [profile.training_plan]);

  const devScore = avgScore(profile.radar_scores);
  let trend: number | null = null;
  if (history.length >= 2) {
    const prev = avgScore(history[history.length - 2].radar_scores);
    const curr = avgScore(history[history.length - 1].radar_scores);
    if (prev !== null && curr !== null) trend = Math.round((curr - prev) * 10) / 10;
  }

  const focus = profile.weaknesses[0] ?? null;
  const strength = profile.strengths[0] ?? null;

  const coachMessage = focus
    ? `This week, give ${focus} the most attention — it's the fastest lever in your game right now.`
    : "Upload your next match and I'll keep your development picture up to date.";

  return (
    <div className="border border-[var(--color-border)] rounded-xl bg-[var(--color-card)] p-4">
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <OverviewCell label="Latest match" value={latestVideo ? (latestVideo.opponent_name ? `vs ${latestVideo.opponent_name}` : latestVideo.original_filename) : "—"} sub={latestVideo?.result_summary ?? undefined} />
        <OverviewCell
          label="Development score"
          value={devScore !== null ? `${Math.round(devScore)}` : "—"}
          sub={trend !== null ? `${trend >= 0 ? "▲" : "▼"} ${Math.abs(trend)} vs last session` : `${profile.matches_analyzed_count} matches analyzed`}
          accent={trend !== null ? (trend >= 0 ? "good" : "warn") : undefined}
        />
        <OverviewCell label="Improvement focus" value={focus ? capitalize(focus) : "—"} accent="warn" />
        <OverviewCell label="Main strength" value={strength ? capitalize(strength) : "—"} accent="good" />
        <OverviewCell label="Next drill" value={drillName ?? "—"} />
        <OverviewCell label="Weekly theme" value={profile.training_plan?.weekly_theme?.replace("This week: focus on ", "") ?? "—"} />
      </div>
      <p className="text-xs text-[var(--color-ink-soft)] mt-3 flex items-center gap-2">
        <span className="w-5 h-5 rounded-full bg-[var(--color-accent)] text-white flex items-center justify-center text-[10px] shrink-0">C</span>
        <span className="italic">“{coachMessage}”</span>
      </p>
    </div>
  );
}

function OverviewCell({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: "good" | "warn" }) {
  const accentColor = accent === "good" ? "text-[var(--color-good)]" : accent === "warn" ? "text-[var(--color-warn)]" : "";
  return (
    <div className="min-w-0">
      <p className="text-[10px] uppercase tracking-wide text-[var(--color-ink-soft)]">{label}</p>
      <p className={`text-sm font-semibold truncate ${accentColor}`} title={value}>{value}</p>
      {sub && <p className="text-[10px] text-[var(--color-ink-soft)] truncate">{sub}</p>}
    </div>
  );
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
