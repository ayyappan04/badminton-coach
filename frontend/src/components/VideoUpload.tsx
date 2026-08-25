import { useRef, useState } from "react";
import { api } from "../api/client";
import type { Video } from "../types";

export function VideoUpload({ onUploaded }: { onUploaded: (video: Video) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [matchFormat, setMatchFormat] = useState("singles");
  const [opponentName, setOpponentName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleFile(file: File) {
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      form.append("match_format", matchFormat);
      if (opponentName) form.append("opponent_name", opponentName);
      const video = await api.postForm<Video>("/videos", form);
      await api.post(`/videos/${video.id}/process`);
      onUploaded(video);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="border border-dashed border-[var(--separator)] rounded-xl p-6 bg-[var(--surface)]">
      <h3 className="font-medium mb-3">Upload a match</h3>
      <div className="flex flex-wrap gap-3 mb-3">
        <select
          value={matchFormat}
          onChange={(e) => setMatchFormat(e.target.value)}
          className="border border-[var(--separator)] rounded-md px-2 py-1.5 text-sm"
        >
          <option value="singles">Singles</option>
          <option value="doubles">Doubles</option>
          <option value="unknown">Not sure</option>
        </select>
        <input
          placeholder="Opponent name (optional)"
          value={opponentName}
          onChange={(e) => setOpponentName(e.target.value)}
          className="border border-[var(--separator)] rounded-md px-2 py-1.5 text-sm flex-1 min-w-[160px]"
        />
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="video/mp4,video/quicktime,.mp4,.mov,.m4v,.avi"
        className="hidden"
        onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
      />
      <button
        onClick={() => inputRef.current?.click()}
        disabled={busy}
        className="bg-[var(--accent)] text-white px-4 py-2 rounded-md font-medium disabled:opacity-50"
      >
        {busy ? "Uploading..." : "Choose video file"}
      </button>
      {error && <p className="text-sm text-[var(--negative)] mt-2">{error}</p>}
      <p className="text-xs text-[var(--text-secondary)] mt-3">
        Supported: .mp4, .mov, .m4v, .avi. Tripod, baseline, side-court, or elevated recordings all
        work — clearer, more direct angles give more reliable results.
      </p>
    </div>
  );
}
