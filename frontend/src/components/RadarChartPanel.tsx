import { Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis, ResponsiveContainer } from "recharts";
import type { ScoreEntry } from "../types";

export const DIMENSION_LABELS: Record<string, string> = {
  attack: "Attack",
  control: "Control",
  endurance: "Endurance",
  defense: "Defense",
  mobility: "Mobility",
  net_play: "Net play",
  power: "Power",
  consistency: "Consistency",
  tactical_awareness: "Tactical awareness",
};

export function RadarChartPanel({
  radarScores,
  height = 280,
  showCaption = true,
}: {
  radarScores: Record<string, ScoreEntry>;
  height?: number;
  showCaption?: boolean;
}) {
  const entries = Object.entries(radarScores);
  if (entries.length === 0) {
    return (
      <p className="text-sm text-[var(--color-ink-soft)]">
        Your play-style radar will appear here once at least one match has been fully analyzed.
      </p>
    );
  }

  const data = entries.map(([key, val]) => ({
    dimension: DIMENSION_LABELS[key] || key,
    score: val.score ?? 0,
  }));

  const avgConfidence =
    entries.reduce((acc, [, v]) => acc + v.confidence, 0) / entries.length;

  return (
    <div>
      <ResponsiveContainer width="100%" height={height}>
        <RadarChart data={data} outerRadius="72%">
          <PolarGrid stroke="var(--color-border-strong)" />
          <PolarAngleAxis dataKey="dimension" tick={{ fontSize: 11, fill: "var(--color-ink-soft)" }} />
          <PolarRadiusAxis type="number" angle={30} domain={[0, 100]} tickCount={5} tick={{ fontSize: 9, fill: "var(--color-ink-soft)" }} stroke="var(--color-border)" />
          <Radar dataKey="score" stroke="var(--color-accent)" strokeWidth={2} fill="var(--color-accent)" fillOpacity={0.35} isAnimationActive={false} />
        </RadarChart>
      </ResponsiveContainer>
      {showCaption && (
        <p className="text-xs text-[var(--color-ink-soft)] text-center">
          Average confidence: {Math.round(avgConfidence * 100)}% — improves as you analyze more matches.
        </p>
      )}
    </div>
  );
}
