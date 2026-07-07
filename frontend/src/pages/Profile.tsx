import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, Tooltip } from "recharts";
import { api } from "../api/client";
import { useAuth } from "../context/AuthContext";
import type { PlayerProfile } from "../types";
import { RadarChartPanel, DIMENSION_LABELS } from "../components/RadarChartPanel";
import { TrainingPlanPanel } from "../components/TrainingPlanPanel";

interface HistorySnapshot {
  snapshot_at: string;
  radar_scores: Record<string, { score: number | null; confidence: number }>;
  video_id: string;
}

export function Profile() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [profile, setProfile] = useState<PlayerProfile | null>(null);
  const [history, setHistory] = useState<HistorySnapshot[]>([]);

  useEffect(() => {
    api.get<PlayerProfile>("/profile").then(setProfile).catch(() => {});
    api.get<HistorySnapshot[]>("/profile/history").then(setHistory).catch(() => {});
  }, []);

  if (!profile) {
    return <div className="max-w-5xl mx-auto px-4 py-12 text-sm text-[var(--color-ink-soft)]">Loading profile...</div>;
  }

  const hasData = profile.matches_analyzed_count > 0;

  return (
    <div className="max-w-5xl mx-auto px-4 py-8 space-y-8">
      {/* Header */}
      <div className="bg-[var(--color-card)] border border-[var(--color-border)] rounded-xl p-6 flex flex-wrap items-center gap-5">
        <span className="w-16 h-16 rounded-full bg-[var(--color-accent)] text-white flex items-center justify-center text-2xl font-semibold shrink-0">
          {user?.display_name?.charAt(0).toUpperCase() ?? "?"}
        </span>
        <div className="min-w-0">
          <h1 className="text-xl font-semibold">{user?.display_name}</h1>
          <p className="text-sm text-[var(--color-ink-soft)]">
            {hasData
              ? `${profile.matches_analyzed_count} match${profile.matches_analyzed_count === 1 ? "" : "es"} analyzed`
              : "No matches analyzed yet"}
          </p>
          {profile.play_style_labels.length > 0 && (
            <div className="flex gap-2 mt-2 flex-wrap">
              {profile.play_style_labels.map((l) => (
                <span key={l.label} className="text-xs bg-[var(--color-accent-soft)] text-[var(--color-accent)] px-2.5 py-1 rounded-full">
                  {l.label} · {Math.round(l.confidence * 100)}%
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {!hasData ? (
        <div className="bg-[var(--color-card)] border border-[var(--color-border)] rounded-xl p-8 text-center">
          <p className="text-[var(--color-ink-soft)] mb-4">
            Your player profile builds automatically as you upload and analyze matches — attribute
            scores, play-style classification, strengths, and a personalized training plan.
          </p>
          <button
            onClick={() => navigate("/dashboard?upload=1")}
            className="bg-[var(--color-accent)] text-white px-5 py-2.5 rounded-md font-medium hover:bg-[var(--color-accent-dark)]"
          >
            Upload your first match
          </button>
        </div>
      ) : (
        <>
          {/* Spider chart + attribute stats */}
          <div className="grid lg:grid-cols-2 gap-6">
            <section className="bg-[var(--color-card)] border border-[var(--color-border)] rounded-xl p-5">
              <h2 className="font-semibold mb-2">Attribute radar</h2>
              <RadarChartPanel radarScores={profile.radar_scores} height={340} />
            </section>

            <section className="bg-[var(--color-card)] border border-[var(--color-border)] rounded-xl p-5">
              <h2 className="font-semibold mb-4">Attribute breakdown</h2>
              <div className="space-y-3">
                {Object.entries(profile.radar_scores).map(([key, entry]) => (
                  <div key={key}>
                    <div className="flex justify-between text-xs mb-1">
                      <span className="text-[var(--color-ink-soft)]">{DIMENSION_LABELS[key] || key}</span>
                      <span className="font-medium">
                        {entry.score !== null ? Math.round(entry.score) : "—"}
                        <span className="text-[var(--color-ink-soft)] font-normal"> / 100</span>
                      </span>
                    </div>
                    <div className="h-2 bg-white/10 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-[var(--color-accent-dark)] to-[var(--color-accent)]"
                        style={{ width: `${entry.score ?? 0}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
              <p className="text-xs text-[var(--color-ink-soft)] mt-4">
                Scores are heuristic composites of video-derived signals, not validated performance
                metrics — treat them as directional and expect them to stabilize over more matches.
              </p>
            </section>
          </div>

          {/* Strengths & weaknesses */}
          <div className="grid sm:grid-cols-2 gap-6">
            <section className="bg-[var(--color-card)] border border-[var(--color-border)] rounded-xl p-5">
              <h2 className="font-semibold mb-3 text-[var(--color-good)]">Strengths</h2>
              {profile.strengths.length > 0 ? (
                <ul className="space-y-2">
                  {profile.strengths.map((s) => (
                    <li key={s} className="text-sm flex items-center gap-2 capitalize">
                      <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-good)] shrink-0" />
                      {s}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-[var(--color-ink-soft)]">No clear standout strengths yet — more matches will sharpen this.</p>
              )}
            </section>
            <section className="bg-[var(--color-card)] border border-[var(--color-border)] rounded-xl p-5">
              <h2 className="font-semibold mb-3 text-[var(--color-warn)]">Areas to improve</h2>
              {profile.weaknesses.length > 0 ? (
                <ul className="space-y-2">
                  {profile.weaknesses.map((w) => (
                    <li key={w} className="text-sm flex items-center gap-2 capitalize">
                      <span className="w-1.5 h-1.5 rounded-full bg-[var(--color-warn)] shrink-0" />
                      {w}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-[var(--color-ink-soft)]">Nothing flagged yet.</p>
              )}
            </section>
          </div>

          {/* Play style evidence */}
          {profile.play_style_labels.length > 0 && (
            <section className="bg-[var(--color-card)] border border-[var(--color-border)] rounded-xl p-5">
              <h2 className="font-semibold mb-3">Play style — and the evidence behind it</h2>
              <div className="space-y-3">
                {profile.play_style_labels.map((l) => (
                  <div key={l.label} className="border border-[var(--color-border)] rounded-lg p-3 bg-[var(--color-bg-raised)]">
                    <div className="flex justify-between items-baseline">
                      <span className="font-medium text-sm">{l.label}</span>
                      <span className="text-xs text-[var(--color-ink-soft)]">{Math.round(l.confidence * 100)}% confidence</span>
                    </div>
                    <p className="text-xs text-[var(--color-ink-soft)] mt-1">{l.evidence}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Progress over time */}
          {history.length >= 2 && (
            <section className="bg-[var(--color-card)] border border-[var(--color-border)] rounded-xl p-5">
              <h2 className="font-semibold mb-3">Progress over time</h2>
              <ProgressChart history={history} />
            </section>
          )}

          {/* Training plan */}
          <section className="bg-[var(--color-card)] border border-[var(--color-border)] rounded-xl p-5">
            <h2 className="font-semibold mb-3">Training plan</h2>
            <TrainingPlanPanel profile={profile} />
          </section>
        </>
      )}
    </div>
  );
}

function ProgressChart({ history }: { history: HistorySnapshot[] }) {
  const [dimension, setDimension] = useState<string>("average");

  const dimensions = Object.keys(history[history.length - 1]?.radar_scores ?? {});

  const data = history.map((snap, i) => {
    let value: number;
    if (dimension === "average") {
      const scores = Object.values(snap.radar_scores)
        .map((v) => v.score)
        .filter((s): s is number => s !== null);
      value = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;
    } else {
      value = snap.radar_scores[dimension]?.score ?? 0;
    }
    return { session: `Session ${i + 1}`, value: Math.round(value * 10) / 10 };
  });

  return (
    <>
      <div className="flex gap-1.5 flex-wrap mb-3">
        <TrendChip label="Overall" active={dimension === "average"} onClick={() => setDimension("average")} />
        {dimensions.map((d) => (
          <TrendChip
            key={d}
            label={DIMENSION_LABELS[d] || d}
            active={dimension === d}
            onClick={() => setDimension(d)}
          />
        ))}
      </div>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
          <XAxis dataKey="session" tick={{ fontSize: 11, fill: "var(--color-ink-soft)" }} stroke="var(--color-border-strong)" />
          <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: "var(--color-ink-soft)" }} stroke="var(--color-border-strong)" />
          <Tooltip
            contentStyle={{
              background: "var(--color-bg-raised)",
              border: "1px solid var(--color-border-strong)",
              borderRadius: 8,
              color: "var(--color-ink)",
              fontSize: 12,
            }}
          />
          <Line type="monotone" dataKey="value" stroke="var(--color-accent)" strokeWidth={2} dot={{ fill: "var(--color-accent)" }} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
      <p className="text-xs text-[var(--color-ink-soft)] mt-1">
        {dimension === "average" ? "Average attribute score" : `${DIMENSION_LABELS[dimension] || dimension} score`} after each analyzed session — directions matter more than exact values.
      </p>
    </>
  );
}

function TrendChip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`text-[10px] px-2 py-1 rounded-full border transition ${
        active
          ? "bg-[var(--color-accent)] text-white border-[var(--color-accent)]"
          : "border-[var(--color-border)] text-[var(--color-ink-soft)] hover:border-[var(--color-accent)]"
      }`}
    >
      {label}
    </button>
  );
}
