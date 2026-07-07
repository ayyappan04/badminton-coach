import { useMemo, useState } from "react";
import type { Video } from "../types";

const STATUS_LABEL: Record<string, string> = {
  uploaded: "Queued",
  processing: "Analyzing...",
  needs_player_selection: "Needs your input",
  analyzed: "Ready",
  failed: "Failed",
};

const STATUS_COLOR: Record<string, string> = {
  uploaded: "bg-white/10 text-[var(--color-ink-soft)]",
  processing: "bg-[var(--color-accent-soft)] text-[var(--color-accent)]",
  needs_player_selection: "bg-[var(--color-warn-soft)] text-[var(--color-warn)]",
  analyzed: "bg-[var(--color-good-soft)] text-[var(--color-good)]",
  failed: "bg-[var(--color-bad-soft)] text-[var(--color-bad)]",
};

export function MatchLibrary({
  videos,
  selectedId,
  onSelect,
}: {
  videos: Video[];
  selectedId: string | null;
  onSelect: (video: Video) => void;
}) {
  const [formatFilter, setFormatFilter] = useState("all");
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    return videos.filter((v) => {
      if (formatFilter !== "all" && v.match_format !== formatFilter) return false;
      if (search) {
        const haystack = `${v.original_filename} ${v.opponent_name ?? ""} ${v.result_summary ?? ""}`.toLowerCase();
        if (!haystack.includes(search.toLowerCase())) return false;
      }
      return true;
    });
  }, [videos, formatFilter, search]);

  if (videos.length === 0) {
    return <p className="text-sm text-[var(--color-ink-soft)] px-1">No matches uploaded yet.</p>;
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-1.5">
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search opponent…"
          className="flex-1 min-w-0 text-xs border border-[var(--color-border)] rounded-md px-2 py-1.5 focus:outline-none focus:border-[var(--color-accent)]"
        />
        <select
          value={formatFilter}
          onChange={(e) => setFormatFilter(e.target.value)}
          className="text-xs border border-[var(--color-border)] rounded-md px-1.5 py-1.5"
        >
          <option value="all">All</option>
          <option value="singles">Singles</option>
          <option value="doubles">Doubles</option>
        </select>
      </div>
      {filtered.length === 0 && (
        <p className="text-xs text-[var(--color-ink-soft)] px-1">No matches fit the current filter.</p>
      )}
      {filtered.map((v) => (
        <button
          key={v.id}
          onClick={() => onSelect(v)}
          className={`text-left border rounded-lg px-3 py-2 transition ${
            selectedId === v.id
              ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)]"
              : "border-[var(--color-border)] bg-[var(--color-card)] hover:bg-[var(--color-card-hover)]"
          }`}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-sm font-medium truncate">{v.original_filename}</span>
            <span className={`text-[10px] px-1.5 py-0.5 rounded-full whitespace-nowrap ${STATUS_COLOR[v.status] || ""}`}>
              {STATUS_LABEL[v.status] || v.status}
            </span>
          </div>
          <div className="text-xs text-[var(--color-ink-soft)] mt-0.5">
            {v.match_format !== "unknown" ? v.match_format : "format tbd"}
            {v.opponent_name ? ` · vs ${v.opponent_name}` : ""}
            {v.result_summary ? ` · ${v.result_summary}` : ""}
          </div>
          {v.status === "processing" && (
            <div className="mt-1.5 h-1.5 bg-white/10 rounded-full overflow-hidden">
              <div
                className="h-full bg-[var(--color-accent)] transition-all"
                style={{ width: `${v.progress_pct}%` }}
              />
            </div>
          )}
        </button>
      ))}
    </div>
  );
}
