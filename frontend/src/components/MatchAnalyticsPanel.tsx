import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { DoublesRotationBlock, MatchAnalytics, Video } from "../types";
import { DoublesRotationPanel } from "./DoublesRotationPanel";

export function MatchAnalyticsPanel({ video }: { video: Video }) {
  const [analytics, setAnalytics] = useState<MatchAnalytics | null>(null);

  useEffect(() => {
    setAnalytics(null);
    api.get<MatchAnalytics>(`/videos/${video.id}/analytics`).then(setAnalytics).catch(() => {});
  }, [video.id]);

  if (!analytics) {
    return <p className="text-sm text-[var(--color-ink-soft)]">Match analytics appear after you confirm which player is you.</p>;
  }

  const blocks = analytics.blocks;
  const rally = blocks.rally_stats as any;
  const mix = blocks.shot_mix as any;
  const combos = blocks.shot_combinations as any;
  const dominance = blocks.court_dominance as any;
  const fatigue = blocks.fatigue_indicator as any;
  const strategy = blocks.strategy_recommendations as any;
  const doubles = blocks.doubles_rotation as DoublesRotationBlock | undefined;

  return (
    <div className="space-y-4">
      {rally?.available && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatCard label="Rallies" value={rally.rally_count} />
          <StatCard label="Avg rally" value={`${rally.avg_duration_s}s`} />
          <StatCard label="Longest rally" value={`${rally.max_duration_s}s`} />
          <StatCard label="Shots / rally" value={rally.avg_shots_per_rally} />
        </div>
      )}

      <div className="grid lg:grid-cols-2 gap-4">
        {mix?.available && (
          <div className="border border-[var(--color-border)] rounded-lg bg-[var(--color-card)] p-4">
            <BlockHeader title="Your shot mix" confidence={mix.confidence} />
            <div className="space-y-1.5 mt-2">
              {Object.entries(mix.by_type as Record<string, { count: number; pct: number }>).slice(0, 6).map(([type, d]) => (
                <div key={type} className="flex items-center gap-2 text-xs">
                  <span className="w-20 text-[var(--color-ink-soft)] capitalize shrink-0">{type.replace(/_/g, " ")}</span>
                  <div className="flex-1 h-2 bg-white/10 rounded-full overflow-hidden">
                    <div className="h-full bg-[var(--color-accent)]" style={{ width: `${d.pct}%` }} />
                  </div>
                  <span className="w-9 text-right">{d.pct}%</span>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-[var(--color-ink-soft)] mt-2">
              Variety: {mix.shot_variety} shot types used repeatedly · intent: {Object.entries(mix.by_intent as Record<string, number>).map(([k, v]) => `${k} ${v}%`).join(" · ")}
            </p>
          </div>
        )}

        <div className="space-y-4">
          {combos?.available && (
            <div className="border border-[var(--color-border)] rounded-lg bg-[var(--color-card)] p-4">
              <BlockHeader title="Repeated patterns" confidence={combos.confidence} />
              <div className="mt-2 space-y-1">
                {(combos.repeated_pairs as { pattern: string; count: number }[]).map((p) => (
                  <p key={p.pattern} className="text-xs">
                    <span className="capitalize">{p.pattern.replace(/_/g, " ")}</span>
                    <span className="text-[var(--color-ink-soft)]"> — {p.count}×</span>
                  </p>
                ))}
              </div>
              {combos.predictability_ratio != null && combos.predictability_ratio >= 0.3 && (
                <p className="text-[10px] text-[var(--color-warn)] mt-1.5">
                  Your top pattern is {Math.round(combos.predictability_ratio * 100)}% of transitions — readable for opponents.
                </p>
              )}
            </div>
          )}

          {dominance?.available && (
            <div className="border border-[var(--color-border)] rounded-lg bg-[var(--color-card)] p-4">
              <BlockHeader title="Court dominance" confidence={dominance.confidence} />
              <div className="flex items-center gap-2 mt-2 text-xs">
                <span className="text-[var(--color-ink-soft)] w-16">Front {dominance.front_court_pct}%</span>
                <div className="flex-1 h-2.5 rounded-full overflow-hidden flex">
                  <div className="h-full bg-[var(--color-court)]" style={{ width: `${dominance.front_court_pct}%` }} />
                  <div className="h-full bg-[var(--color-accent)]" style={{ width: `${dominance.rear_court_pct}%` }} />
                </div>
                <span className="text-[var(--color-ink-soft)] w-16 text-right">Rear {dominance.rear_court_pct}%</span>
              </div>
            </div>
          )}

          {fatigue?.available && (
            <div className="border border-[var(--color-border)] rounded-lg bg-[var(--color-card)] p-4">
              <BlockHeader title="Movement trend" confidence={fatigue.confidence} />
              <p className="text-xs mt-1.5">
                Movement speed across the match: <span className="capitalize font-medium">{fatigue.movement_speed_trend}</span>
                <span className="text-[var(--color-ink-soft)]"> ({fatigue.relative_change_per_rally_pct > 0 ? "+" : ""}{fatigue.relative_change_per_rally_pct}%/rally over {fatigue.rallies_measured} rallies)</span>
              </p>
              <p className="text-[10px] text-[var(--color-ink-soft)] mt-1">{fatigue.basis}</p>
            </div>
          )}
        </div>
      </div>

      {doubles && (
        <div className="border border-[var(--color-border)] rounded-lg bg-[var(--color-card)] p-4">
          <BlockHeader title="Doubles rotation & formation" confidence={doubles.confidence} />
          <div className="mt-2">
            <DoublesRotationPanel block={doubles} />
          </div>
        </div>
      )}

      {strategy?.available && (
        <div className="border border-[var(--color-border)] rounded-lg bg-[var(--color-card)] p-4">
          <BlockHeader title="Strategy recommendations" confidence={strategy.confidence} />
          <div className="mt-2 space-y-3">
            {(strategy.recommendations as { recommendation: string; evidence: string; confidence: number }[]).map((r, i) => (
              <div key={i} className="border-l-2 border-[var(--color-accent)] pl-3">
                <p className="text-sm">{r.recommendation}</p>
                <p className="text-[10px] text-[var(--color-ink-soft)] mt-0.5">
                  Evidence: {r.evidence} · {Math.round(r.confidence * 100)}% confidence
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="border border-[var(--color-border)] rounded-lg bg-[var(--color-card)] p-3 text-center">
      <p className="text-lg font-semibold">{value}</p>
      <p className="text-[10px] text-[var(--color-ink-soft)]">{label}</p>
    </div>
  );
}

function BlockHeader({ title, confidence }: { title: string; confidence: number }) {
  return (
    <div className="flex items-center justify-between">
      <h3 className="text-sm font-semibold">{title}</h3>
      <span className="text-[10px] text-[var(--color-ink-soft)]">{Math.round(confidence * 100)}% conf.</span>
    </div>
  );
}
