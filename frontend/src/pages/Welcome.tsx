import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { AuthForms } from "../components/AuthForms";
import { CoachChat } from "../components/CoachChat";
import { api } from "../api/client";
import type { PlayerProfile, Video } from "../types";
import {
  Button, Delta, Metric, Page, Skeleton, Surface, formatScore, titleCase,
} from "../ui";

interface HistorySnapshot {
  snapshot_at: string;
  radar_scores: Record<string, { score: number | null; confidence: number }>;
}

function averageScore(scores: Record<string, { score: number | null }> | undefined): number | null {
  if (!scores) return null;
  const values = Object.values(scores).map((v) => v.score).filter((s): s is number => s !== null);
  if (!values.length) return null;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

function averageConfidence(scores: Record<string, { confidence: number }> | undefined): number | null {
  if (!scores) return null;
  const values = Object.values(scores).map((v) => v.confidence).filter((c) => typeof c === "number");
  if (!values.length) return null;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

export function Welcome() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [profile, setProfile] = useState<PlayerProfile | null>(null);
  const [videos, setVideos] = useState<Video[]>([]);
  const [history, setHistory] = useState<HistorySnapshot[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!user) return;
    setLoading(true);
    Promise.allSettled([
      api.get<PlayerProfile>("/profile").then(setProfile),
      api.get<Video[]>("/videos").then(setVideos),
      api.get<HistorySnapshot[]>("/profile/history").then(setHistory),
    ]).finally(() => setLoading(false));
  }, [user]);

  if (!user) return <SignedOut />;

  const analyzed = videos.filter((v) => v.status === "analyzed");
  const latest = analyzed[0] ?? null;
  const hasData = (profile?.matches_analyzed_count ?? 0) > 0;

  const devScore = averageScore(profile?.radar_scores);
  const confidence = averageConfidence(profile?.radar_scores);

  let trend: number | null = null;
  if (history.length >= 2) {
    const prev = averageScore(history[history.length - 2].radar_scores);
    const curr = averageScore(history[history.length - 1].radar_scores);
    if (prev !== null && curr !== null) trend = Math.round((curr - prev) * 10) / 10;
  }

  const focus = profile?.weaknesses?.[0] ?? profile?.training_plan?.priority_areas?.[0] ?? null;
  const strength = profile?.strengths?.[0] ?? null;
  const focusScore = focus
    ? profile?.radar_scores?.[focus.replace(/ /g, "_")]?.score ?? null
    : null;

  return (
    <Page width="narrow">
      <div className="mb-7">
        <h1 className="text-[30px] sm:text-[34px] leading-tight" style={{ color: "var(--text-primary)" }}>
          {greeting()}, {user.display_name}
        </h1>
        <p className="mt-1.5 text-[15px]" style={{ color: "var(--text-secondary)" }}>
          {hasData
            ? `${profile?.matches_analyzed_count} ${profile?.matches_analyzed_count === 1 ? "match" : "matches"} analyzed. Here's where your game stands.`
            : "Upload your first match and I'll start building your player profile."}
        </p>
      </div>

      {loading && !profile ? (
        <Surface className="mb-5">
          <Skeleton className="w-40 mb-4" height={12} />
          <div className="grid grid-cols-3 gap-5">
            {[0, 1, 2].map((i) => (
              <div key={i}>
                <Skeleton className="w-20 mb-2" height={10} />
                <Skeleton className="w-14" height={28} />
              </div>
            ))}
          </div>
        </Surface>
      ) : hasData ? (
        <Surface className="mb-5">
          <div className="text-[11px] font-medium uppercase tracking-wider mb-3" style={{ color: "var(--text-tertiary)" }}>
            Current focus
          </div>
          <div className="flex items-baseline gap-3 flex-wrap mb-5">
            <span className="text-[22px] font-semibold" style={{ color: "var(--text-primary)" }}>
              {focus ? titleCase(focus) : "Building your baseline"}
            </span>
            {focusScore !== null && (
              <span className="tnum text-[15px]" style={{ color: "var(--text-secondary)" }}>
                {formatScore(focusScore)} / 100
              </span>
            )}
          </div>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-5 gap-y-4">
            <Metric
              label="Development score"
              value={formatScore(devScore)}
              size="lg"
              delta={trend !== null ? <Delta value={trend} suffix="vs last" /> : undefined}
            />
            <Metric label="Matches analyzed" value={profile?.matches_analyzed_count ?? 0} size="lg" />
            <Metric
              label="Main strength"
              value={<span className="text-[18px]">{strength ? titleCase(strength) : "—"}</span>}
              size="lg"
            />
            <Metric
              label="Analysis confidence"
              value={confidence !== null ? `${Math.round(confidence * 100)}%` : "—"}
              size="lg"
            />
          </div>

          {focus && (
            <p className="mt-5 pt-4 border-t text-[14px]" style={{ borderColor: "var(--separator)", color: "var(--text-secondary)" }}>
              {titleCase(focus)} is your largest opportunity right now — it scores lowest across your
              analyzed sessions.
              {confidence !== null && confidence < 0.5 && " Confidence is still low, so treat this as a direction rather than a verdict."}
            </p>
          )}
        </Surface>
      ) : null}

      <div className="flex flex-wrap gap-2.5 mb-8">
        {latest ? (
          <>
            <Button variant="primary" onClick={() => navigate(`/dashboard?video=${latest.id}`)}>
              Review latest match
            </Button>
            <Button onClick={() => navigate("/dashboard?upload=1")}>Upload match</Button>
          </>
        ) : (
          <Button variant="primary" onClick={() => navigate("/dashboard?upload=1")}>
            Upload your first match
          </Button>
        )}
      </div>

      <section aria-labelledby="coach-chat-heading">
        <h2
          id="coach-chat-heading"
          className="text-[11px] font-medium uppercase tracking-wider mb-3"
          style={{ color: "var(--text-tertiary)" }}
        >
          Ask your coach
        </h2>
        <CoachChat />
      </section>

      <p className="mt-10 text-[12px] leading-relaxed" style={{ color: "var(--text-tertiary)" }}>
        Coaching is generated from video analysis. Accuracy depends on camera angle, lighting and
        frame rate, so every figure carries a confidence value.
      </p>
    </Page>
  );
}

function SignedOut() {
  return (
    <Page width="narrow" className="pt-16 sm:pt-24">
      <div className="max-w-lg">
        <h1
          className="text-[36px] sm:text-[44px] leading-[1.08] tracking-tight"
          style={{ color: "var(--text-primary)" }}
        >
          See your game
          <br />
          more clearly.
        </h1>
        <p className="mt-4 text-[16px] leading-relaxed" style={{ color: "var(--text-secondary)" }}>
          ShuttleSense turns match footage into measurable coaching insights across technique,
          movement, positioning and tactics.
        </p>
      </div>

      <div className="mt-10 max-w-sm">
        <AuthForms />
      </div>

      <p className="mt-8 text-[12px] leading-relaxed max-w-md" style={{ color: "var(--text-tertiary)" }}>
        Every insight is derived from video and shown with a confidence level. Where the footage
        doesn't support a conclusion, ShuttleSense says so rather than guessing.
      </p>
    </Page>
  );
}
