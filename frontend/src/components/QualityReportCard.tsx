import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { QualityReport, Video } from "../types";
import { ScoreBar, Surface } from "../ui";

const FACTOR_LABELS: Record<string, string> = {
  resolution: "Resolution",
  frame_rate: "Frame rate",
  lighting: "Lighting",
  sharpness: "Sharpness",
  stability: "Camera stability",
  camera_cuts: "Continuity",
};

function verdict(score: number): string {
  if (score >= 70) return "Good";
  if (score >= 45) return "Usable";
  return "Limited";
}

/** Headline quality indicators, with the per-factor breakdown and recording
 *  advice behind a disclosure rather than always on screen. */
export function QualityReportCard({ video }: { video: Video }) {
  const [report, setReport] = useState<QualityReport | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setReport(null);
    api
      .get<QualityReport>(`/videos/${video.id}/quality-report`)
      .then((d) => !cancelled && setReport(d))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [video.id]);

  if (!report) return null;

  const tone =
    report.score >= 70 ? "var(--text-primary)" : report.score >= 45 ? "var(--warning)" : "var(--negative)";

  // Surface the two weakest factors — the actionable part of the report.
  const weakest = Object.entries(report.factors)
    .sort((a, b) => a[1].score - b[1].score)
    .slice(0, 2);

  return (
    <Surface>
      <div className="flex items-baseline justify-between gap-4 flex-wrap">
        <div className="flex items-baseline gap-3">
          <span className="text-[11px] font-medium uppercase tracking-wider" style={{ color: "var(--text-tertiary)" }}>
            Recording quality
          </span>
          <span className="tnum text-[22px] font-semibold" style={{ color: tone }}>
            {report.score}
          </span>
          <span className="text-[13px]" style={{ color: "var(--text-secondary)" }}>
            {verdict(report.score)}
          </span>
        </div>
        <button
          onClick={() => setExpanded((v) => !v)}
          aria-expanded={expanded}
          className="text-[12px] transition-colors"
          style={{ color: "var(--accent)" }}
        >
          {expanded ? "Hide analysis details" : "Analysis details"}
        </button>
      </div>

      {!expanded && weakest.length > 0 && (
        <p className="mt-2 text-[13px]" style={{ color: "var(--text-tertiary)" }}>
          Weakest: {weakest.map(([k, f]) => `${FACTOR_LABELS[k] ?? k} ${Math.round(f.score * 100)}`).join(" · ")}
        </p>
      )}

      {expanded && (
        <div className="mt-4 space-y-4">
          <div className="grid sm:grid-cols-2 gap-x-8 gap-y-3">
            {Object.entries(report.factors).map(([key, f]) => (
              <div key={key}>
                <div className="flex items-baseline justify-between gap-2 mb-1">
                  <span className="text-[13px]" style={{ color: "var(--text-secondary)" }}>
                    {FACTOR_LABELS[key] ?? key}
                  </span>
                  <span className="tnum text-[13px] font-medium" style={{ color: "var(--text-primary)" }}>
                    {Math.round(f.score * 100)}
                  </span>
                </div>
                <ScoreBar value={f.score * 100} />
                <p className="text-[11px] mt-1" style={{ color: "var(--text-tertiary)" }}>
                  {f.detail}
                </p>
              </div>
            ))}
          </div>

          {report.recommendations.length > 0 && (
            <div className="pt-3 border-t" style={{ borderColor: "var(--separator)" }}>
              <p className="text-[11px] font-medium uppercase tracking-wider mb-2" style={{ color: "var(--text-tertiary)" }}>
                To improve future recordings
              </p>
              <ul className="space-y-1.5">
                {report.recommendations.map((r, i) => (
                  <li key={i} className="text-[13px] leading-snug" style={{ color: "var(--text-secondary)" }}>
                    {r}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {report.pipeline_version && (
            <p className="text-[11px]" style={{ color: "var(--text-tertiary)" }}>
              Analyzed with pipeline v{report.pipeline_version}
            </p>
          )}
        </div>
      )}
    </Surface>
  );
}
