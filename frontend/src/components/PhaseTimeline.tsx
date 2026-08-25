import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { RallyWithPhases, Video } from "../types";
import { formatTimestamp } from "../ui";

/* Restrained palette: blue carries neutral play, warm hues mark pressure
   moments. Deliberately not six saturated colours competing for attention. */
const PHASE_COLORS: Record<string, string> = {
  serve: "#7c6df2",
  return: "#4aa3e0",
  attack: "#e8724c",
  neutral: "#3d8bfd",
  defense: "#f0b35c",
  ending: "#d8556b",
};

const PHASE_LABELS: Record<string, string> = {
  serve: "Serve",
  return: "Return",
  attack: "Attack",
  neutral: "Neutral",
  defense: "Defense",
  ending: "Rally end",
};

export function PhaseTimeline({ video, onSeek }: { video: Video; onSeek: (t: number) => void }) {
  const [rallies, setRallies] = useState<RallyWithPhases[] | null>(null);
  const [hover, setHover] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setRallies(null);
    api
      .get<RallyWithPhases[]>(`/videos/${video.id}/phases`)
      .then((d) => !cancelled && setRallies(d))
      .catch(() => !cancelled && setRallies([]));
    return () => {
      cancelled = true;
    };
  }, [video.id]);

  if (rallies === null) {
    return <div className="h-10 rounded-[var(--radius-md)]" style={{ background: "var(--surface-sunken)" }} />;
  }

  if (!rallies.length) {
    return (
      <p className="text-[13px]" style={{ color: "var(--text-tertiary)" }}>
        No rallies were segmented for this video.
      </p>
    );
  }

  const duration = video.duration_seconds || Math.max(...rallies.map((r) => r.end_timestamp_s), 1);
  const hasPhases = rallies.some((r) => r.phases && r.phases.length > 0);
  const totalShots = rallies.reduce((acc, r) => acc + r.shot_count, 0);
  const usedPhases = new Set(rallies.flatMap((r) => (r.phases ?? []).map((p) => p.phase)));

  return (
    <div>
      <div
        className="relative h-10 rounded-[var(--radius-md)] overflow-hidden"
        style={{ background: "var(--surface-sunken)", border: "1px solid var(--separator)" }}
      >
        {rallies.map((rally) => {
          const left = (rally.start_timestamp_s / duration) * 100;
          const width = Math.max(0.5, ((rally.end_timestamp_s - rally.start_timestamp_s) / duration) * 100);
          const summary = `Rally ${rally.rally_index + 1} · ${formatTimestamp(rally.start_timestamp_s)} · ${rally.shot_count} shots${
            rally.ending_shot_type ? ` · ends on ${rally.ending_shot_type.replace(/_/g, " ")}` : ""
          }`;
          return (
            <button
              key={rally.rally_index}
              className="absolute top-0 h-full group focus-visible:z-10"
              style={{ left: `${left}%`, width: `${width}%` }}
              onClick={() => onSeek(rally.start_timestamp_s)}
              onMouseEnter={() => setHover(summary)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(summary)}
              onBlur={() => setHover(null)}
              aria-label={`Jump to ${summary}`}
            >
              {(rally.phases ?? []).map((phase, i) => {
                const span = rally.end_timestamp_s - rally.start_timestamp_s || 1;
                const pLeft = ((phase.start_s - rally.start_timestamp_s) / span) * 100;
                const pWidth = Math.max(2, ((phase.end_s - phase.start_s) / span) * 100);
                return (
                  <span
                    key={i}
                    className="absolute top-0 h-full opacity-85 group-hover:opacity-100 transition-opacity"
                    style={{
                      left: `${Math.max(0, pLeft)}%`,
                      width: `${Math.min(100 - Math.max(0, pLeft), pWidth)}%`,
                      backgroundColor: PHASE_COLORS[phase.phase] ?? PHASE_COLORS.neutral,
                    }}
                    title={`${PHASE_LABELS[phase.phase] ?? phase.phase} · ${Math.round(phase.confidence * 100)}% confidence`}
                  />
                );
              })}
              {(!rally.phases || !rally.phases.length) && (
                <span className="absolute inset-0" style={{ background: "var(--accent)", opacity: 0.45 }} />
              )}
            </button>
          );
        })}
      </div>

      <div className="mt-2 flex items-start justify-between gap-4 flex-wrap">
        <p className="text-[12px] min-h-[18px] tnum" style={{ color: hover ? "var(--text-secondary)" : "var(--text-tertiary)" }}>
          {hover ?? `${rallies.length} rallies · ${totalShots} tracked shots${hasPhases ? "" : " · confirm your identity to unlock phases"}`}
        </p>
        {hasPhases && (
          <ul className="flex gap-3 flex-wrap">
            {Object.entries(PHASE_LABELS)
              .filter(([key]) => usedPhases.has(key))
              .map(([key, label]) => (
                <li key={key} className="flex items-center gap-1.5 text-[11px]" style={{ color: "var(--text-tertiary)" }}>
                  <span
                    className="w-2 h-2 rounded-[2px] inline-block"
                    style={{ backgroundColor: PHASE_COLORS[key] }}
                    aria-hidden="true"
                  />
                  {label}
                </li>
              ))}
          </ul>
        )}
      </div>
    </div>
  );
}
