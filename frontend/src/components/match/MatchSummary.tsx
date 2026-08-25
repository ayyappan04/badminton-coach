import type { MatchAnalytics, Video } from "../../types";
import { Metric, Skeleton, Surface, formatScore } from "../../ui";
import { DIMENSION_GROUPS, meanConfidence, meanScore, type Scorecards } from "./matchData";

/** The analytical anchor of a match: overall standing, the three coaching
 *  areas, and how much of it the analysis could actually observe. */
export function MatchSummary({
  video,
  cards,
  analytics,
  loading,
}: {
  video: Video;
  cards: Scorecards | null;
  analytics: MatchAnalytics | null;
  loading: boolean;
}) {
  const allKeys = Object.keys(cards ?? {});
  const overall = meanScore(cards, allKeys);
  const movement = meanScore(cards, DIMENSION_GROUPS.movement);
  const technique = meanScore(cards, DIMENSION_GROUPS.technique);
  const stability = meanScore(cards, DIMENSION_GROUPS.stability);
  const confidence = meanConfidence(cards);

  const rally = analytics?.blocks?.rally_stats as
    | { available?: boolean; rally_count?: number; avg_shots_per_rally?: number }
    | undefined;
  const mix = analytics?.blocks?.shot_mix as { available?: boolean; total_shots?: number } | undefined;
  const observations = mix?.total_shots ?? null;

  if (loading) {
    return (
      <Surface>
        <Skeleton className="w-32 mb-4" height={11} />
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-5">
          {[0, 1, 2, 3].map((i) => (
            <div key={i}>
              <Skeleton className="w-16 mb-2" height={10} />
              <Skeleton className="w-12" height={30} />
            </div>
          ))}
        </div>
      </Surface>
    );
  }

  if (overall.value === null) {
    return (
      <Surface>
        <p className="text-[14px]" style={{ color: "var(--text-secondary)" }}>
          Technique scoring isn't available for this match.
        </p>
        <p className="text-[13px] mt-1" style={{ color: "var(--text-tertiary)" }}>
          {video.status === "needs_player_selection"
            ? "Confirm which tracked player is you and scores will be generated."
            : "The footage didn't yield enough clean tracking to score performance."}
        </p>
      </Surface>
    );
  }

  return (
    <Surface>
      <div
        className="text-[11px] font-medium uppercase tracking-wider mb-4"
        style={{ color: "var(--text-tertiary)" }}
      >
        Match performance
      </div>

      <div className="flex flex-wrap items-start gap-x-10 gap-y-6">
        <Metric
          label={`Overall · mean of ${overall.n} measured ${overall.n === 1 ? "dimension" : "dimensions"}`}
          value={formatScore(overall.value)}
          unit="/ 100"
          size="hero"
        />

        <div className="grid grid-cols-3 gap-x-8 gap-y-4 flex-1 min-w-[240px]">
          <AreaScore label="Movement" score={movement} />
          <AreaScore label="Technique" score={technique} />
          <AreaScore label="Stability" score={stability} />
        </div>
      </div>

      <div
        className="mt-5 pt-4 border-t grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-3"
        style={{ borderColor: "var(--separator)" }}
      >
        <Metric
          label="Analysis confidence"
          value={confidence !== null ? `${Math.round(confidence * 100)}%` : "—"}
          size="sm"
        />
        <Metric label="Tracked shots" value={observations ?? "—"} size="sm" />
        <Metric label="Rallies" value={rally?.rally_count ?? "—"} size="sm" />
        <Metric
          label="Recording quality"
          value={video.quality_score ?? "—"}
          unit={video.quality_score !== null && video.quality_score !== undefined ? "/ 100" : undefined}
          size="sm"
        />
      </div>

      {confidence !== null && confidence < 0.5 && (
        <p className="mt-4 text-[13px]" style={{ color: "var(--warning)" }}>
          Confidence is low across this match — read these as directional signals rather than
          measurements.
        </p>
      )}
    </Surface>
  );
}

function AreaScore({ label, score }: { label: string; score: { value: number | null; n: number } }) {
  const unavailable = score.value === null;
  return (
    <div style={unavailable ? { opacity: 0.55 } : undefined}>
      <div className="text-[12px]" style={{ color: "var(--text-tertiary)" }}>
        {label}
      </div>
      <div className="tnum text-[24px] font-semibold mt-0.5" style={{ color: "var(--text-primary)" }}>
        {unavailable ? "—" : formatScore(score.value)}
      </div>
      <div className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>
        {unavailable ? "not measured" : `${score.n} ${score.n === 1 ? "metric" : "metrics"}`}
      </div>
    </div>
  );
}
