import { useMemo, useState } from "react";
import type { Video } from "../types";
import { Button, EmptyState, SegmentedControl, StatusLabel, formatDate } from "../ui";

type FormatFilter = "all" | "singles" | "doubles";

/** Match library. Whole rows are selectable; each row leads with identity and
 *  status, then one line of analytical context — not every metadata field. */
export function MatchLibrary({
  videos,
  selectedId,
  onSelect,
  onUpload,
}: {
  videos: Video[];
  selectedId: string | null;
  onSelect: (video: Video) => void;
  onUpload?: () => void;
}) {
  const [format, setFormat] = useState<FormatFilter>("all");
  const [query, setQuery] = useState("");

  const filtered = useMemo(
    () =>
      videos.filter((v) => {
        if (format !== "all" && v.match_format !== format) return false;
        if (query) {
          const haystack = `${v.original_filename} ${v.opponent_name ?? ""} ${v.result_summary ?? ""}`.toLowerCase();
          if (!haystack.includes(query.toLowerCase())) return false;
        }
        return true;
      }),
    [videos, format, query],
  );

  if (!videos.length) {
    return (
      <EmptyState
        title="No matches yet"
        description="Upload your first match to begin building your player profile."
        action={onUpload ? <Button variant="primary" onClick={onUpload}>Upload match</Button> : undefined}
      />
    );
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search opponent or file…"
          aria-label="Search matches"
          className="flex-1 min-w-[150px] !h-9 !min-h-0 !py-1.5 !text-[13px]"
        />
        <SegmentedControl
          size="sm"
          ariaLabel="Filter by match format"
          value={format}
          onChange={setFormat}
          options={[
            { value: "all", label: "All" },
            { value: "singles", label: "Singles" },
            { value: "doubles", label: "Doubles" },
          ]}
        />
      </div>

      {!filtered.length ? (
        <p className="text-[13px] py-4" style={{ color: "var(--text-tertiary)" }}>
          No matches fit the current filter.
        </p>
      ) : (
        <ul className="divide-y" style={{ borderColor: "var(--separator)" }}>
          {filtered.map((v) => (
            <li key={v.id}>
              <MatchRow video={v} selected={v.id === selectedId} onSelect={() => onSelect(v)} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MatchRow({ video, selected, onSelect }: { video: Video; selected: boolean; onSelect: () => void }) {
  const title = video.opponent_name ? `vs ${video.opponent_name}` : video.original_filename;
  const processing = video.status === "processing" || video.status === "uploaded";
  const dateLabel = formatDate(video.recorded_at ?? null);

  return (
    <button
      onClick={onSelect}
      aria-current={selected ? "true" : undefined}
      className="w-full text-left px-3 py-3 -mx-3 rounded-[var(--radius-md)] transition-colors hover:bg-[var(--surface-hover)]"
      style={selected ? { background: "var(--accent-soft)" } : undefined}
    >
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[14px] font-medium truncate" style={{ color: "var(--text-primary)" }}>
          {title}
        </span>
        <StatusLabel status={video.status} className="shrink-0" />
      </div>

      <div className="mt-1 flex items-center gap-2 text-[12px] min-w-0" style={{ color: "var(--text-tertiary)" }}>
        <span className="shrink-0 capitalize">
          {dateLabel !== "—" ? dateLabel : video.match_format !== "unknown" ? video.match_format : "Match"}
        </span>
        {video.result_summary && (
          <>
            <Dot />
            <span className="truncate" style={{ color: "var(--text-secondary)" }}>
              {video.result_summary}
            </span>
          </>
        )}
        {video.quality_score !== null && video.quality_score !== undefined && (
          <>
            <Dot />
            <span className="tnum shrink-0">Quality {video.quality_score}</span>
          </>
        )}
      </div>

      {processing && (
        <div
          className="mt-2 h-1 rounded-[var(--radius-full)] overflow-hidden"
          style={{ background: "var(--surface-sunken)" }}
          role="progressbar"
          aria-valuenow={video.progress_pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Analysis progress"
        >
          <div
            className="h-full transition-[width] duration-500"
            style={{ width: `${video.progress_pct}%`, background: "var(--accent)" }}
          />
        </div>
      )}
    </button>
  );
}

function Dot() {
  return (
    <span className="shrink-0" aria-hidden="true" style={{ opacity: 0.5 }}>
      ·
    </span>
  );
}
