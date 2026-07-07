import { useState } from "react";
import { api } from "../api/client";
import type { CompareSummary, Video } from "../types";

const ROWS: { key: keyof CompareSummary; label: string; unit?: string }[] = [
  { key: "rally_count", label: "Rallies" },
  { key: "avg_rally_duration_s", label: "Avg rally duration", unit: "s" },
  { key: "avg_shots_per_rally", label: "Shots per rally" },
  { key: "total_shots", label: "Tracked shots" },
  { key: "shot_variety", label: "Shot variety" },
  { key: "offensive_pct", label: "Offensive shots", unit: "%" },
  { key: "defensive_pct", label: "Defensive shots", unit: "%" },
  { key: "front_court_pct", label: "Front-court time", unit: "%" },
  { key: "quality_score", label: "Recording quality" },
];

export function CompareDrawer({ current, videos }: { current: Video; videos: Video[] }) {
  const [otherId, setOtherId] = useState<string>("");
  const [result, setResult] = useState<{ a: CompareSummary; b: CompareSummary } | null>(null);
  const [loading, setLoading] = useState(false);

  const candidates = videos.filter((v) => v.id !== current.id && v.status === "analyzed");

  async function runCompare(id: string) {
    setOtherId(id);
    if (!id) {
      setResult(null);
      return;
    }
    setLoading(true);
    try {
      const data = await api.get<{ a: CompareSummary; b: CompareSummary }>(`/videos/compare/${current.id}/${id}`);
      setResult(data);
    } finally {
      setLoading(false);
    }
  }

  if (candidates.length === 0) {
    return <p className="text-sm text-[var(--color-ink-soft)]">Analyze a second match to unlock match comparison.</p>;
  }

  return (
    <div className="border border-[var(--color-border)] rounded-lg bg-[var(--color-card)] p-4">
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-sm font-medium">Compare this match with:</span>
        <select
          value={otherId}
          onChange={(e) => runCompare(e.target.value)}
          className="text-xs border border-[var(--color-border)] rounded-md px-2 py-1.5"
        >
          <option value="">Select a match…</option>
          {candidates.map((v) => (
            <option key={v.id} value={v.id}>
              {v.opponent_name ? `vs ${v.opponent_name}` : v.original_filename}
            </option>
          ))}
        </select>
        {loading && <span className="text-xs text-[var(--color-ink-soft)]">Comparing…</span>}
      </div>

      {result && (
        <div className="mt-4">
          <div className="grid grid-cols-[1fr_auto_auto] gap-x-6 gap-y-1.5 text-xs">
            <span className="text-[var(--color-ink-soft)]" />
            <span className="font-medium text-right">{shortName(result.a)}</span>
            <span className="font-medium text-right">{shortName(result.b)}</span>
            {ROWS.map(({ key, label, unit }) => {
              const a = result.a[key] as number | null;
              const b = result.b[key] as number | null;
              return (
                <Row key={key} label={label} a={a} b={b} unit={unit} />
              );
            })}
          </div>
          <p className="text-[10px] text-[var(--color-ink-soft)] mt-3">{result.a.confidence_note}</p>
        </div>
      )}
    </div>
  );
}

function Row({ label, a, b, unit }: { label: string; a: number | null; b: number | null; unit?: string }) {
  const better = a !== null && b !== null && a !== b ? (a > b ? "a" : "b") : null;
  return (
    <>
      <span className="text-[var(--color-ink-soft)]">{label}</span>
      <span className={`text-right ${better === "a" ? "text-[var(--color-good)] font-medium" : ""}`}>
        {a ?? "—"}{a !== null && unit ? unit : ""}
      </span>
      <span className={`text-right ${better === "b" ? "text-[var(--color-good)] font-medium" : ""}`}>
        {b ?? "—"}{b !== null && unit ? unit : ""}
      </span>
    </>
  );
}

function shortName(s: CompareSummary): string {
  return s.opponent_name ? `vs ${s.opponent_name}` : s.filename.slice(0, 18);
}
