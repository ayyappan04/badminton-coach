import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { MatchAnalytics, Shot, Video } from "../../types";
import {
  Confidence, DataTable, Delta, EmptyState, Metric, MetricGroup, MetricRow,
  ScoreBar, SectionHeader, SkeletonRows, Surface, formatRatioPercent,
  formatTimestamp, titleCase,
} from "../../ui";
import { DIMENSION_GROUPS, DIMENSION_LABELS, type Scorecards } from "./matchData";
import { HeatmapPanel } from "../HeatmapPanel";
import { InsightsPanel } from "../InsightsPanel";
import { PhaseTimeline } from "../PhaseTimeline";
import { QualityReportCard } from "../QualityReportCard";
import { CoachReviewSection } from "../CoachReviewSection";
import { DoublesRotationPanel } from "../DoublesRotationPanel";

/** Scored dimensions rendered as grouped rows — one surface per concept,
 *  never one card per number. */
export function DimensionList({ cards, keys }: { cards: Scorecards | null; keys: readonly string[] }) {
  const present = keys.filter((k) => cards && k in cards);
  if (!cards || !present.length) {
    return (
      <p className="text-[13px]" style={{ color: "var(--text-tertiary)" }}>
        Not measured in this match.
      </p>
    );
  }
  return (
    <div className="space-y-3.5">
      {present.map((key) => {
        const entry = cards[key];
        const score = entry.score;
        const low = entry.confidence > 0 && entry.confidence < 0.45;
        return (
          <div key={key} style={low ? { opacity: 0.62 } : undefined}>
            <div className="flex items-baseline justify-between gap-3 mb-1.5">
              <span className="text-[14px]" style={{ color: "var(--text-secondary)" }}>
                {DIMENSION_LABELS[key] ?? titleCase(key)}
              </span>
              <span className="flex items-baseline gap-2">
                <span className="tnum text-[16px] font-semibold" style={{ color: "var(--text-primary)" }}>
                  {score === null || score === undefined ? "—" : Math.round(score)}
                </span>
                <Confidence value={entry.confidence} />
              </span>
            </div>
            <ScoreBar value={score} />
            <p className="text-[11.5px] mt-1.5 leading-snug" style={{ color: "var(--text-tertiary)" }}>
              {entry.basis}
            </p>
          </div>
        );
      })}
    </div>
  );
}

/* ---------------------------------------------------------------- Overview */

export function OverviewTab({
  video,
  analytics,
  onSeek,
  onOpenStudio,
}: {
  video: Video;
  analytics: MatchAnalytics | null;
  onSeek: (t: number) => void;
  onOpenStudio: (name: string, t: number) => void;
}) {
  const strategy = analytics?.blocks?.strategy_recommendations as
    | { available?: boolean; recommendations?: { recommendation: string; evidence: string; confidence: number }[] }
    | undefined;

  return (
    <div className="space-y-5">
      <QualityReportCard video={video} />

      <Surface>
        <SectionHeader
          title="Rally timeline"
          description="Each segment is a phase of play. Select one to jump the video there."
        />
        <PhaseTimeline video={video} onSeek={onSeek} />
      </Surface>

      <Surface>
        <SectionHeader title="Coaching insights" description="Findings linked to the moments they came from." />
        <InsightsPanel video={video} onSeek={onSeek} onOpenTechnique={onOpenStudio} />
      </Surface>

      {strategy?.available && strategy.recommendations?.length ? (
        <Surface>
          <SectionHeader title="Strategy" description="Patterns worth adjusting, with the evidence behind each." />
          <div className="space-y-4">
            {strategy.recommendations.map((r, i) => (
              <div key={i} className="pl-3 border-l-2" style={{ borderColor: "var(--accent-line)" }}>
                <p className="text-[14px]" style={{ color: "var(--text-primary)" }}>
                  {r.recommendation}
                </p>
                <p className="text-[12px] mt-1 flex flex-wrap items-center gap-x-2" style={{ color: "var(--text-tertiary)" }}>
                  <span>{r.evidence}</span>
                  <Confidence value={r.confidence} showLabel />
                </p>
              </div>
            ))}
          </div>
        </Surface>
      ) : null}

      <Surface>
        <SectionHeader title="Coach review" description="Invite a coach to annotate this match." />
        <CoachReviewSection video={video} onSeek={onSeek} />
      </Surface>
    </div>
  );
}

/* ---------------------------------------------------------------- Movement */

export function MovementTab({
  video,
  cards,
  analytics,
}: {
  video: Video;
  cards: Scorecards | null;
  analytics: MatchAnalytics | null;
}) {
  const dominance = analytics?.blocks?.court_dominance as
    | { available?: boolean; front_court_pct?: number; rear_court_pct?: number; confidence?: number; basis?: string }
    | undefined;
  const fatigue = analytics?.blocks?.fatigue_indicator as
    | {
        available?: boolean;
        movement_speed_trend?: string;
        relative_change_per_rally_pct?: number;
        rallies_measured?: number;
        confidence?: number;
        basis?: string;
      }
    | undefined;

  return (
    <div className="grid lg:grid-cols-2 gap-5 items-start">
      <Surface>
        <SectionHeader title="Movement quality" description="Video-based estimates of how you move and recover." />
        <DimensionList cards={cards} keys={DIMENSION_GROUPS.movement} />
      </Surface>

      <div className="space-y-5">
        {dominance?.available && (
          <Surface>
            <SectionHeader title="Court dominance" />
            <div className="flex h-2 rounded-[var(--radius-full)] overflow-hidden mb-2.5">
              <div style={{ width: `${dominance.front_court_pct}%`, background: "var(--accent)" }} />
              <div style={{ width: `${dominance.rear_court_pct}%`, background: "var(--viz-series-2)" }} />
            </div>
            <MetricGroup>
              <MetricRow label="Front court" value={dominance.front_court_pct} unit="%" />
              <MetricRow label="Rear court" value={dominance.rear_court_pct} unit="%" />
            </MetricGroup>
            <p className="text-[11.5px] mt-2.5 leading-snug" style={{ color: "var(--text-tertiary)" }}>
              {dominance.basis}
            </p>
          </Surface>
        )}

        {fatigue?.available && (
          <Surface>
            <SectionHeader title="Movement over the match" />
            <Metric
              label="Speed trend"
              value={titleCase(fatigue.movement_speed_trend ?? "—")}
              size="md"
              delta={
                fatigue.relative_change_per_rally_pct !== undefined ? (
                  <Delta value={fatigue.relative_change_per_rally_pct} unit="%" decimals={1} suffix="per rally" />
                ) : undefined
              }
              detail={`${fatigue.rallies_measured} rallies measured`}
              confidence={fatigue.confidence ?? null}
              muted={(fatigue.confidence ?? 0) < 0.45}
            />
            <p className="text-[11.5px] mt-2.5 leading-snug" style={{ color: "var(--text-tertiary)" }}>
              {fatigue.basis}
            </p>
          </Surface>
        )}
      </div>

      <Surface className="lg:col-span-2">
        <SectionHeader title="Court coverage" description="Where you spent time on court." />
        <HeatmapPanel video={video} />
      </Surface>
    </div>
  );
}

/* --------------------------------------------------------------- Technique */

export function TechniqueTab({
  cards,
  onOpenStudio,
}: {
  cards: Scorecards | null;
  onOpenStudio: (name: string, t: number) => void;
}) {
  return (
    <div className="grid lg:grid-cols-2 gap-5 items-start">
      <Surface>
        <SectionHeader title="Stroke technique" description="Estimated from body landmarks at contact." />
        <DimensionList cards={cards} keys={DIMENSION_GROUPS.technique} />
      </Surface>

      <div className="space-y-5">
        <Surface>
          <SectionHeader title="Balance & stability" />
          <DimensionList cards={cards} keys={DIMENSION_GROUPS.stability} />
        </Surface>

        <Surface>
          <SectionHeader
            title="Comparison studio"
            description="Play your clip beside a reference movement, frame by frame."
          />
          <div className="flex flex-wrap gap-2">
            {["overhead_clear", "smash", "net_lunge", "split_step"].map((name) => (
              <button
                key={name}
                onClick={() => onOpenStudio(name, 0)}
                className="h-9 px-3 rounded-[var(--radius-md)] border text-[13px] transition-colors hover:bg-[var(--surface-hover)]"
                style={{ borderColor: "var(--separator-strong)", color: "var(--text-secondary)" }}
              >
                {titleCase(name)}
              </button>
            ))}
          </div>
        </Surface>
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------- Tactics */

export function TacticsTab({ analytics }: { analytics: MatchAnalytics | null }) {
  const combos = analytics?.blocks?.shot_combinations as
    | {
        available?: boolean;
        repeated_pairs?: { pattern: string; count: number }[];
        repeated_triples?: { pattern: string; count: number }[];
        predictability_ratio?: number | null;
        confidence?: number;
        basis?: string;
      }
    | undefined;
  const pressure = analytics?.blocks?.pressure_zones as
    | { available?: boolean; opponent_hot_zones?: { row: number; col: number; occupancy: number }[]; confidence?: number; basis?: string }
    | undefined;
  const serve = analytics?.blocks?.serve_patterns as
    | { available?: boolean; serves?: { tracked: number; by_self: number } | null; returns?: { tracked: number; by_self: number } | null; confidence?: number; basis?: string }
    | undefined;
  const doubles = analytics?.blocks?.doubles_rotation as any;

  const anything = combos?.available || pressure?.available || serve?.available || doubles;
  if (!anything) {
    return <EmptyState title="No tactical patterns detected" description="This match didn't yield enough tracked shots to mine patterns from." />;
  }

  return (
    <div className="grid lg:grid-cols-2 gap-5 items-start">
      {combos?.available && (
        <Surface>
          <SectionHeader title="Repeated patterns" description="Sequences an opponent could learn to read." />
          {combos.predictability_ratio != null && (
            <div className="mb-4">
              <Metric
                label="Share of your most common transition"
                value={`${Math.round(combos.predictability_ratio * 100)}%`}
                size="lg"
                confidence={combos.confidence ?? null}
              />
            </div>
          )}
          <MetricGroup>
            {(combos.repeated_pairs ?? []).map((p) => (
              <MetricRow key={p.pattern} label={p.pattern} value={p.count} unit="×" />
            ))}
            {(combos.repeated_triples ?? []).map((p) => (
              <MetricRow key={p.pattern} label={p.pattern} value={p.count} unit="×" />
            ))}
          </MetricGroup>
          <p className="text-[11.5px] mt-2.5 leading-snug" style={{ color: "var(--text-tertiary)" }}>
            {combos.basis}
          </p>
        </Surface>
      )}

      {serve?.available && (
        <Surface>
          <SectionHeader title="Serve & return" />
          <MetricGroup>
            {serve.serves && <MetricRow label="Serves tracked" value={serve.serves.tracked} />}
            {serve.serves && <MetricRow label="Yours" value={serve.serves.by_self} />}
            {serve.returns && <MetricRow label="Returns tracked" value={serve.returns.tracked} />}
            {serve.returns && <MetricRow label="Yours" value={serve.returns.by_self} />}
          </MetricGroup>
          <p className="text-[11.5px] mt-2.5 leading-snug" style={{ color: "var(--text-tertiary)" }}>
            {serve.basis}
          </p>
        </Surface>
      )}

      {pressure?.available && (
        <Surface>
          <SectionHeader title="Opponent pressure zones" description="Where your opponent held position most." />
          <MetricGroup>
            {(pressure.opponent_hot_zones ?? []).map((z, i) => (
              <MetricRow
                key={i}
                label={`Zone row ${z.row}, column ${z.col}`}
                value={formatRatioPercent(z.occupancy)}
              />
            ))}
          </MetricGroup>
          <p className="text-[11.5px] mt-2.5 leading-snug" style={{ color: "var(--text-tertiary)" }}>
            {pressure.basis}
          </p>
        </Surface>
      )}

      {doubles && (
        <Surface className="lg:col-span-2">
          <SectionHeader title="Doubles rotation" />
          <DoublesRotationPanel block={doubles} />
        </Surface>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------- Shots */

export function ShotsTab({ video, analytics, onSeek }: { video: Video; analytics: MatchAnalytics | null; onSeek: (t: number) => void }) {
  const [shots, setShots] = useState<Shot[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    setShots(null);
    api.get<Shot[]>(`/videos/${video.id}/shots`).then((d) => !cancelled && setShots(d)).catch(() => !cancelled && setShots([]));
    return () => {
      cancelled = true;
    };
  }, [video.id]);

  const mix = analytics?.blocks?.shot_mix as
    | {
        available?: boolean;
        total_shots?: number;
        shot_variety?: number;
        by_type?: Record<string, { count: number; pct: number }>;
        by_intent?: Record<string, number>;
        confidence?: number;
        basis?: string;
      }
    | undefined;

  const rally = analytics?.blocks?.rally_stats as
    | { available?: boolean; rally_count?: number; avg_duration_s?: number; max_duration_s?: number; avg_shots_per_rally?: number; confidence?: number }
    | undefined;

  return (
    <div className="space-y-5">
      {rally?.available && (
        <Surface>
          <SectionHeader title="Rally shape" />
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-4">
            <Metric label="Rallies" value={rally.rally_count ?? "—"} />
            <Metric label="Average length" value={rally.avg_duration_s ?? "—"} unit="s" />
            <Metric label="Longest" value={rally.max_duration_s ?? "—"} unit="s" />
            <Metric label="Shots per rally" value={rally.avg_shots_per_rally ?? "—"} />
          </div>
        </Surface>
      )}

      {mix?.available && mix.by_type && (
        <Surface>
          <SectionHeader
            title="Shot mix"
            description={`${mix.total_shots} tracked shots · ${mix.shot_variety} types used more than once`}
            action={<Confidence value={mix.confidence ?? null} showLabel />}
          />
          <DataTable
            columns={[
              { key: "type", header: "Shot", align: "left", render: (r: [string, { count: number; pct: number }]) => titleCase(r[0]) },
              { key: "count", header: "Count", align: "right", render: (r) => r[1].count },
              { key: "pct", header: "Share", align: "right", render: (r) => `${r[1].pct}%` },
            ]}
            rows={Object.entries(mix.by_type)}
            getRowKey={(r) => r[0]}
          />
          <p className="text-[11.5px] mt-3 leading-snug" style={{ color: "var(--text-tertiary)" }}>
            {mix.basis}
          </p>
        </Surface>
      )}

      <Surface>
        <SectionHeader
          title="Every tracked shot"
          description="Select a row to jump the video to that moment."
        />
        {shots === null ? (
          <SkeletonRows rows={4} />
        ) : (
          <DataTable
            columns={[
              { key: "t", header: "Time", align: "left", render: (s: Shot) => formatTimestamp(s.timestamp_s) },
              { key: "type", header: "Shot", align: "left", render: (s) => titleCase(s.shot_type) },
              { key: "contact", header: "Contact", align: "left", render: (s) => titleCase(s.contact_height) },
              { key: "intent", header: "Intent", align: "left", render: (s) => titleCase(s.intent) },
              { key: "conf", header: "Confidence", align: "right", render: (s) => `${Math.round(s.confidence * 100)}%` },
            ]}
            rows={shots}
            getRowKey={(s, i) => `${s.timestamp_s}-${i}`}
            onRowClick={(s) => onSeek(s.timestamp_s)}
            empty="No shots were detected in this match."
          />
        )}
        <p className="text-[11.5px] mt-3 leading-snug" style={{ color: "var(--text-tertiary)" }}>
          Shot labels come from a rule-based heuristic, not a trained classifier — counts are
          indicative rather than exact.
        </p>
      </Surface>
    </div>
  );
}
