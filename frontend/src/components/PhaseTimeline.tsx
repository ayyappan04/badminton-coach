import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { RallyWithPhases, Video } from "../types";

const PHASE_COLORS: Record<string, string> = {
  serve: "#8b5cf6",
  return: "#0ea5e9",
  attack: "#f0553d",
  neutral: "#3d8bfd",
  defense: "#f0b35c",
  ending: "#e5484d",
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
  const [rallies, setRallies] = useState<RallyWithPhases[]>([]);
  const [hover, setHover] = useState<string | null>(null);

  useEffect(() => {
    api.get<RallyWithPhases[]>(`/videos/${video.id}/phases`).then(setRallies).catch(() => setRallies([]));
  }, [video.id]);

  const duration = video.duration_seconds || Math.max(...rallies.map((r) => r.end_timestamp_s), 1);

  if (rallies.length === 0) {
    return (
      <div>
        <h3 className="text-sm font-semibold mb-2">Rally &amp; phase timeline</h3>
        <p className="text-xs text-[var(--color-ink-soft)]">No rallies segmented for this video.</p>
      </div>
    );
  }

  const hasPhases = rallies.some((r) => r.phases && r.phases.length > 0);
  const totalShots = rallies.reduce((acc, r) => acc + r.shot_count, 0);

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold">Rally &amp; phase timeline</h3>
        <div className="flex gap-3 flex-wrap">
          {Object.entries(PHASE_LABELS).map(([key, label]) => (
            <span key={key} className="flex items-center gap-1 text-[10px] text-[var(--color-ink-soft)]">
              <span className="w-2 h-2 rounded-sm inline-block" style={{ backgroundColor: PHASE_COLORS[key] }} />
              {label}
            </span>
          ))}
        </div>
      </div>
      <div className="relative h-9 bg-white/5 border border-[var(--color-border)] rounded-md overflow-hidden">
        {rallies.map((rally) => {
          const left = (rally.start_timestamp_s / duration) * 100;
          const width = Math.max(0.5, ((rally.end_timestamp_s - rally.start_timestamp_s) / duration) * 100);
          return (
            <div
              key={rally.rally_index}
              className="absolute top-0 h-full cursor-pointer group"
              style={{ left: `${left}%`, width: `${width}%` }}
              onClick={() => onSeek(rally.start_timestamp_s)}
              onMouseEnter={() => setHover(`Rally ${rally.rally_index + 1} · ${rally.shot_count} shots · ${Math.round(rally.end_timestamp_s - rally.start_timestamp_s)}s${rally.ending_shot_type ? ` · ends on ${rally.ending_shot_type.replace(/_/g, " ")} (${rally.ending_track_role})` : ""}`)}
              onMouseLeave={() => setHover(null)}
            >
              {(rally.phases || []).map((phase, i) => {
                const rallySpan = rally.end_timestamp_s - rally.start_timestamp_s || 1;
                const pLeft = ((phase.start_s - rally.start_timestamp_s) / rallySpan) * 100;
                const pWidth = Math.max(2, ((phase.end_s - phase.start_s) / rallySpan) * 100);
                return (
                  <div
                    key={i}
                    className="absolute top-0 h-full opacity-80 group-hover:opacity-100 transition-opacity"
                    style={{
                      left: `${Math.max(0, pLeft)}%`,
                      width: `${Math.min(100 - Math.max(0, pLeft), pWidth)}%`,
                      backgroundColor: PHASE_COLORS[phase.phase] || PHASE_COLORS.neutral,
                    }}
                    onClick={(e) => {
                      e.stopPropagation();
                      onSeek(phase.start_s);
                    }}
                    title={`${PHASE_LABELS[phase.phase] || phase.phase} · ${Math.round(phase.confidence * 100)}%`}
                  />
                );
              })}
              {(!rally.phases || rally.phases.length === 0) && (
                <div className="absolute inset-0 bg-[var(--color-court)]/60" />
              )}
            </div>
          );
        })}
      </div>
      <p className="text-xs text-[var(--color-ink-soft)] mt-1.5 min-h-4">
        {hover ??
          `${rallies.length} rallies · ${totalShots} tracked shots · click any segment to jump the video there${hasPhases ? "" : " · confirm your identity to unlock phase colors"}`}
      </p>
    </div>
  );
}
