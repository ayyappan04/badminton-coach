import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { QualityReport, Video } from "../types";

const FACTOR_LABELS: Record<string, string> = {
  resolution: "Resolution",
  frame_rate: "Frame rate",
  lighting: "Lighting",
  sharpness: "Sharpness",
  stability: "Camera stability",
  camera_cuts: "Continuity",
};

export function QualityReportCard({ video }: { video: Video }) {
  const [report, setReport] = useState<QualityReport | null>(null);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    setReport(null);
    api.get<QualityReport>(`/videos/${video.id}/quality-report`).then(setReport).catch(() => {});
  }, [video.id]);

  if (!report) return null;

  const scoreColor =
    report.score >= 70 ? "var(--color-good)" : report.score >= 45 ? "var(--color-warn)" : "var(--color-bad)";

  return (
    <div className="border border-[var(--color-border)] rounded-lg bg-[var(--color-card)] p-4">
      <button className="w-full flex items-center justify-between" onClick={() => setExpanded((v) => !v)}>
        <div className="flex items-center gap-3">
          <div
            className="w-11 h-11 rounded-full flex items-center justify-center text-sm font-bold border-2"
            style={{ borderColor: scoreColor, color: scoreColor }}
          >
            {report.score}
          </div>
          <div className="text-left">
            <p className="text-sm font-semibold">Recording quality</p>
            <p className="text-xs text-[var(--color-ink-soft)]">
              {report.score >= 70 ? "Good footage for analysis" : report.score >= 45 ? "Usable — some limits apply" : "Limited — analysis is partial"}
              {report.pipeline_version ? ` · pipeline v${report.pipeline_version}` : ""}
            </p>
          </div>
        </div>
        <span className="text-xs text-[var(--color-accent)]">{expanded ? "Hide details" : "Details"}</span>
      </button>

      {expanded && (
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
            {Object.entries(report.factors).map(([key, f]) => (
              <div key={key} className="border border-[var(--color-border)] rounded-md p-2 bg-[var(--color-bg-raised)]">
                <div className="flex justify-between text-xs mb-1">
                  <span className="text-[var(--color-ink-soft)]">{FACTOR_LABELS[key] || key}</span>
                  <span>{Math.round(f.score * 100)}</span>
                </div>
                <div className="h-1.5 bg-white/10 rounded-full overflow-hidden">
                  <div className="h-full bg-[var(--color-accent)]" style={{ width: `${f.score * 100}%` }} />
                </div>
                <p className="text-[10px] text-[var(--color-ink-soft)] mt-1">{f.detail}</p>
              </div>
            ))}
          </div>
          <div>
            <p className="text-xs font-medium mb-1">Recording tips</p>
            <ul className="space-y-1">
              {report.recommendations.map((r, i) => (
                <li key={i} className="text-xs text-[var(--color-ink-soft)] flex gap-1.5">
                  <span className="text-[var(--color-accent)] shrink-0">•</span> {r}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}
