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

/** Multidimensional shape only — the numbers live beside it so nobody has to
 *  estimate a value from a polygon. */
export function RadarChartPanel({
  radarScores,
  height = 300,
  showCaption = true,
}: {
  radarScores: Record<string, ScoreEntry>;
  height?: number;
  showCaption?: boolean;
}) {
  const entries = Object.entries(radarScores);
  if (!entries.length) {
    return (
      <p className="text-[13px]" style={{ color: "var(--text-tertiary)" }}>
        Your attribute profile appears once a match has been fully analyzed.
      </p>
    );
  }

  const data = entries.map(([key, val]) => ({
    dimension: DIMENSION_LABELS[key] ?? key,
    score: val.score ?? 0,
  }));

  const avgConfidence = entries.reduce((acc, [, v]) => acc + v.confidence, 0) / entries.length;

  return (
    <div>
      <ResponsiveContainer width="100%" height={height}>
        <RadarChart data={data} outerRadius="70%">
          <PolarGrid stroke="var(--viz-grid)" strokeWidth={1} />
          <PolarAngleAxis
            dataKey="dimension"
            tick={{ fontSize: 11, fill: "var(--text-tertiary)" }}
          />
          <PolarRadiusAxis
            type="number"
            angle={90}
            domain={[0, 100]}
            tickCount={5}
            tick={{ fontSize: 9, fill: "var(--text-tertiary)" }}
            stroke="transparent"
            axisLine={false}
          />
          <Radar
            dataKey="score"
            stroke="var(--accent)"
            strokeWidth={2}
            fill="var(--accent)"
            fillOpacity={0.22}
            isAnimationActive={false}
          />
        </RadarChart>
      </ResponsiveContainer>
      {showCaption && (
        <p className="text-[11.5px] text-center" style={{ color: "var(--text-tertiary)" }}>
          Average confidence {Math.round(avgConfidence * 100)}% — rises as you analyze more matches.
        </p>
      )}
    </div>
  );
}
