import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "../api/client";
import { useAuth } from "../context/AuthContext";
import type { PlayerProfile } from "../types";
import { RadarChartPanel, DIMENSION_LABELS } from "../components/RadarChartPanel";
import { TrainingPlanPanel } from "../components/TrainingPlanPanel";
import {
  Button, Confidence, Delta, EmptyState, Metric, Page, PageHeader, ScoreBar,
  SectionHeader, SegmentedControl, Skeleton, Sparkline, Surface, formatScore, titleCase,
} from "../ui";

interface HistorySnapshot {
  snapshot_at: string;
  radar_scores: Record<string, { score: number | null; confidence: number }>;
  video_id: string;
}

function mean(values: number[]): number | null {
  if (!values.length) return null;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

function overallOf(scores: Record<string, { score: number | null }>): number | null {
  return mean(Object.values(scores).map((v) => v.score).filter((s): s is number => s !== null));
}

export function Profile() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [profile, setProfile] = useState<PlayerProfile | null>(null);
  const [history, setHistory] = useState<HistorySnapshot[]>([]);
  const [loading, setLoading] = useState(true);
  const [trendDim, setTrendDim] = useState<string>("overall");

  useEffect(() => {
    Promise.allSettled([
      api.get<PlayerProfile>("/profile").then(setProfile),
      api.get<HistorySnapshot[]>("/profile/history").then(setHistory),
    ]).finally(() => setLoading(false));
  }, []);

  const dimensionKeys = useMemo(
    () => (profile ? Object.keys(profile.radar_scores) : []),
    [profile],
  );

  const trendData = useMemo(
    () =>
      history.map((snap, i) => ({
        session: `S${i + 1}`,
        value:
          trendDim === "overall"
            ? overallOf(snap.radar_scores)
            : snap.radar_scores[trendDim]?.score ?? null,
      })),
    [history, trendDim],
  );

  if (loading) {
    return (
      <Page>
        <Skeleton className="w-56 mb-3" height={30} />
        <Skeleton className="w-80 mb-8" height={14} />
        <Surface>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-6">
            {[0, 1, 2, 3].map((i) => (
              <div key={i}>
                <Skeleton className="w-20 mb-2" height={10} />
                <Skeleton className="w-16" height={32} />
              </div>
            ))}
          </div>
        </Surface>
      </Page>
    );
  }

  const hasData = (profile?.matches_analyzed_count ?? 0) > 0;

  if (!profile || !hasData) {
    return (
      <Page>
        <PageHeader title="Progress" description="Your development across analyzed sessions." />
        <Surface>
          <EmptyState
            title="No analyzed sessions yet"
            description="Your attribute profile, trends and training plan build automatically as you upload matches."
            action={<Button variant="primary" onClick={() => navigate("/dashboard?upload=1")}>Upload your first match</Button>}
          />
        </Surface>
      </Page>
    );
  }

  const overall = overallOf(profile.radar_scores);
  const firstOverall = history.length ? overallOf(history[0].radar_scores) : null;
  const sinceStart = overall !== null && firstOverall !== null ? Math.round((overall - firstOverall) * 10) / 10 : null;
  const avgConfidence = mean(Object.values(profile.radar_scores).map((v) => v.confidence));
  const focus = profile.weaknesses[0] ?? null;

  const overallSeries = history
    .map((s) => overallOf(s.radar_scores))
    .filter((v): v is number => v !== null);

  return (
    <Page>
      <PageHeader
        title="Progress"
        description={`${profile.matches_analyzed_count} ${profile.matches_analyzed_count === 1 ? "session" : "sessions"} analyzed for ${user?.display_name ?? "you"}.`}
      />

      {/* Hero: where the player stands right now */}
      <Surface className="mb-5">
        <div className="flex flex-wrap items-start gap-x-10 gap-y-6">
          <Metric
            label="Overall development"
            value={formatScore(overall)}
            unit="/ 100"
            size="hero"
            delta={sinceStart !== null ? <Delta value={sinceStart} suffix="since first session" /> : undefined}
          />
          {overallSeries.length >= 2 && (
            <div className="pt-4">
              <Sparkline points={overallSeries} width={110} height={30} />
              <p className="text-[11px] mt-1" style={{ color: "var(--text-tertiary)" }}>
                {overallSeries.length} sessions
              </p>
            </div>
          )}
          <div className="grid grid-cols-2 gap-x-8 gap-y-4 flex-1 min-w-[220px]">
            <Metric label="Current focus" value={<span className="text-[18px]">{focus ? titleCase(focus) : "—"}</span>} size="lg" />
            <Metric
              label="Analysis confidence"
              value={avgConfidence !== null ? `${Math.round(avgConfidence * 100)}%` : "—"}
              size="lg"
            />
          </div>
        </div>

        {profile.play_style_labels.length > 0 && (
          <div className="mt-5 pt-4 border-t" style={{ borderColor: "var(--separator)" }}>
            <p className="text-[11px] font-medium uppercase tracking-wider mb-2" style={{ color: "var(--text-tertiary)" }}>
              Play style
            </p>
            <div className="space-y-2">
              {profile.play_style_labels.map((l) => (
                <div key={l.label}>
                  <div className="flex items-baseline gap-2">
                    <span className="text-[14px] font-medium" style={{ color: "var(--text-primary)" }}>
                      {l.label}
                    </span>
                    <Confidence value={l.confidence} showLabel />
                  </div>
                  <p className="text-[12.5px] leading-snug mt-0.5" style={{ color: "var(--text-tertiary)" }}>
                    {l.evidence}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}
      </Surface>

      {/* Radar + numeric breakdown side by side */}
      <div className="grid lg:grid-cols-2 gap-5 items-start mb-5">
        <Surface>
          <SectionHeader title="Attribute profile" />
          <RadarChartPanel radarScores={profile.radar_scores} />
        </Surface>

        <Surface>
          <SectionHeader title="Attribute breakdown" description="Every dimension, with its measured value." />
          <div className="space-y-3">
            {Object.entries(profile.radar_scores).map(([key, entry]) => {
              const prev =
                history.length >= 2 ? history[history.length - 2].radar_scores[key]?.score ?? null : null;
              const change = entry.score !== null && prev !== null ? Math.round((entry.score - prev) * 10) / 10 : null;
              const low = entry.confidence > 0 && entry.confidence < 0.45;
              return (
                <div key={key} style={low ? { opacity: 0.62 } : undefined}>
                  <div className="flex items-baseline justify-between gap-3 mb-1.5">
                    <span className="text-[14px]" style={{ color: "var(--text-secondary)" }}>
                      {DIMENSION_LABELS[key] ?? titleCase(key)}
                    </span>
                    <span className="flex items-baseline gap-2.5">
                      {change !== null && change !== 0 && <Delta value={change} decimals={1} />}
                      <span className="tnum text-[16px] font-semibold" style={{ color: "var(--text-primary)" }}>
                        {entry.score === null ? "—" : Math.round(entry.score)}
                      </span>
                    </span>
                  </div>
                  <ScoreBar value={entry.score} />
                </div>
              );
            })}
          </div>
          <p className="text-[11.5px] mt-4 leading-snug" style={{ color: "var(--text-tertiary)" }}>
            Scores are heuristic composites of video-derived signals, not validated performance
            metrics — read them as directional and expect them to settle as sessions accumulate.
          </p>
        </Surface>
      </div>

      {/* Strengths and focus areas */}
      <div className="grid sm:grid-cols-2 gap-5 mb-5">
        <Surface>
          <SectionHeader title="Strengths" />
          {profile.strengths.length ? (
            <ul className="space-y-2.5">
              {profile.strengths.map((s) => {
                const key = s.replace(/ /g, "_");
                const score = profile.radar_scores[key]?.score ?? null;
                return (
                  <li key={s} className="flex items-baseline justify-between gap-3">
                    <span className="text-[14px] capitalize" style={{ color: "var(--text-primary)" }}>
                      {s}
                    </span>
                    <span className="tnum text-[15px] font-semibold" style={{ color: "var(--positive)" }}>
                      {formatScore(score)}
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="text-[13px]" style={{ color: "var(--text-tertiary)" }}>
              No standout strengths yet — more sessions will sharpen this.
            </p>
          )}
        </Surface>

        <Surface>
          <SectionHeader title="Focus areas" />
          {profile.weaknesses.length ? (
            <ul className="space-y-2.5">
              {profile.weaknesses.map((w) => {
                const key = w.replace(/ /g, "_");
                const score = profile.radar_scores[key]?.score ?? null;
                return (
                  <li key={w} className="flex items-baseline justify-between gap-3">
                    <span className="text-[14px] capitalize" style={{ color: "var(--text-primary)" }}>
                      {w}
                    </span>
                    <span className="tnum text-[15px] font-semibold" style={{ color: "var(--warning)" }}>
                      {formatScore(score)}
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="text-[13px]" style={{ color: "var(--text-tertiary)" }}>
              Nothing flagged yet.
            </p>
          )}
        </Surface>
      </div>

      {/* Longitudinal trend */}
      <Surface className="mb-5">
        <SectionHeader
          title="Progress over time"
          description="Score after each analyzed session."
          action={
            history.length >= 2 ? (
              <SegmentedControl
                size="sm"
                ariaLabel="Trend dimension"
                value={trendDim}
                onChange={setTrendDim}
                options={[
                  { value: "overall", label: "Overall" },
                  ...dimensionKeys.slice(0, 5).map((k) => ({ value: k, label: DIMENSION_LABELS[k] ?? titleCase(k) })),
                ]}
              />
            ) : undefined
          }
        />
        {history.length < 2 ? (
          <EmptyState
            compact
            title="Trends appear after two sessions"
            description="Upload another match to start plotting your development."
          />
        ) : (
          <ResponsiveContainer width="100%" height={220}>
            <LineChart data={trendData} margin={{ top: 8, right: 12, bottom: 0, left: -20 }}>
              <CartesianGrid stroke="var(--viz-grid)" vertical={false} />
              <XAxis dataKey="session" tick={{ fontSize: 11, fill: "var(--text-tertiary)" }} tickLine={false} axisLine={false} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: "var(--text-tertiary)" }} tickLine={false} axisLine={false} />
              <Tooltip
                cursor={{ stroke: "var(--separator-strong)" }}
                contentStyle={{
                  background: "var(--surface-raised)",
                  border: "1px solid var(--separator-strong)",
                  borderRadius: "var(--radius-md)",
                  color: "var(--text-primary)",
                  fontSize: 12,
                  boxShadow: "var(--shadow-md)",
                }}
                labelStyle={{ color: "var(--text-tertiary)" }}
              />
              <Line
                type="monotone"
                dataKey="value"
                name={trendDim === "overall" ? "Overall" : DIMENSION_LABELS[trendDim] ?? trendDim}
                stroke="var(--accent)"
                strokeWidth={2}
                dot={{ fill: "var(--accent)", r: 3 }}
                isAnimationActive={false}
                connectNulls
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </Surface>

      <Surface>
        <SectionHeader title="Training plan" description="What to work on next, and why." />
        <TrainingPlanPanel profile={profile} />
      </Surface>
    </Page>
  );
}
