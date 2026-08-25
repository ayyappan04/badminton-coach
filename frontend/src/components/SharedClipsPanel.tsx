import { useEffect, useState } from "react";
import { api, getToken } from "../api/client";
import type { SharedClipItem } from "../types";

/** Phase 3: clips you saved plus clips friends shared with you, each playable
 * in place (the stream endpoint enforces ownership, so friends' clips only
 * play when the underlying video allows it). */
export function SharedClipsPanel({ currentUserId }: { currentUserId: string }) {
  const [clips, setClips] = useState<SharedClipItem[]>([]);
  const [playing, setPlaying] = useState<string | null>(null);

  useEffect(() => {
    api.get<SharedClipItem[]>("/clips/shared").then(setClips).catch(() => {});
  }, []);

  if (clips.length === 0) {
    return (
      <p className="text-sm text-[var(--text-secondary)]">
        No clips yet. Use "Share clip" on any coaching insight to save a moment here.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      {clips.map((c) => (
        <div key={c.clip_id} className="border border-[var(--separator)] rounded-lg bg-[var(--surface)] p-3">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm truncate">{c.caption || "Shared clip"}</p>
              <p className="text-xs text-[var(--text-secondary)]">
                {formatTime(c.clip_start_s)}–{formatTime(c.clip_end_s)} ·{" "}
                <span className="capitalize">{c.visibility}</span>
                {c.created_by_user_id === currentUserId ? " · yours" : ""}
              </p>
            </div>
            <button
              onClick={() => setPlaying(playing === c.clip_id ? null : c.clip_id)}
              className="text-xs border border-[var(--accent)] text-[var(--accent)] rounded-md px-3 py-1.5 shrink-0 hover:bg-[var(--accent-soft)]"
            >
              {playing === c.clip_id ? "Hide" : "▶ Play"}
            </button>
          </div>
          {playing === c.clip_id && <ClipPlayer clip={c} />}
        </div>
      ))}
    </div>
  );
}

function ClipPlayer({ clip }: { clip: SharedClipItem }) {
  const src = `/api/v1/videos/${clip.video_id}/stream?token=${encodeURIComponent(getToken() || "")}#t=${clip.clip_start_s},${clip.clip_end_s}`;
  return (
    <video
      src={src}
      controls
      autoPlay
      className="w-full max-h-64 mt-2 rounded-md bg-black/40"
      onTimeUpdate={(e) => {
        const v = e.currentTarget;
        if (v.currentTime > clip.clip_end_s) v.pause();
      }}
    />
  );
}

function formatTime(s: number): string {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${sec.toString().padStart(2, "0")}`;
}
