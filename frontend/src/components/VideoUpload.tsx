import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Video } from "../types";
import { inspect, formatClipDuration, type Preflight } from "../lib/preflight";
import {
  cancelUpload, formatBytes, formatDuration, startUpload,
  type UploadHandle, type UploadProgress,
} from "../lib/upload";
import { Button, Surface } from "../ui";

/* ==========================================================================
   Large-video upload.

   Two things this screen is careful about:

   1. Uploading and processing are different states, shown differently. The old
      version left "Uploading..." on screen while the server analysed the
      match, which told the user something false for several minutes.

   2. It never invents a time estimate. Throughput is measured over a trailing
      window and the estimate appears only once there is enough evidence for it
      to mean anything.
   ========================================================================== */

type Phase = "idle" | "selected" | "uploading" | "paused" | "finalizing" | "queued" | "error";

interface ActiveUpload {
  video_id: string;
  original_filename: string;
  expected_size_bytes: number;
  received_size_bytes: number;
  match_format: string;
  opponent_name: string | null;
}

export function VideoUpload({ onUploaded }: { onUploaded: (video: Video) => void }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const handleRef = useRef<UploadHandle | null>(null);

  const [matchFormat, setMatchFormat] = useState("singles");
  const [opponentName, setOpponentName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [preflight, setPreflight] = useState<Preflight | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [resumable, setResumable] = useState<ActiveUpload[]>([]);

  /* --- refresh recovery ---------------------------------------------------
     Upload state lives server-side, so reloading the page mid-upload shows
     what was in flight instead of an empty form. No job state is held only in
     React memory.
     ---------------------------------------------------------------------- */
  useEffect(() => {
    api.get<ActiveUpload[]>("/videos/uploads/active")
      .then(setResumable)
      .catch(() => setResumable([]));
  }, []);

  /* Warn only while bytes are actually moving. Blocking navigation during
     server-side processing would be wrong: the user can safely leave. */
  useEffect(() => {
    if (phase !== "uploading") return;
    const warn = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [phase]);

  const pickFile = useCallback(async (picked: File) => {
    setFile(picked);
    setError(null);
    setProgress(null);
    setPhase("selected");
    setPreflight(await inspect(picked));
  }, []);

  async function begin() {
    if (!file) return;
    setPhase("uploading");
    setError(null);
    try {
      handleRef.current = await startUpload({
        file,
        matchFormat,
        opponentName: opponentName.trim() || undefined,
        onProgress: setProgress,
        onError: (message) => { setError(message); setPhase("error"); },
        onSuccess: async (videoId) => {
          setPhase("finalizing");
          try {
            const video = await api.get<Video>(`/videos/${videoId}`);
            setPhase("queued");
            onUploaded(video);
            reset();
          } catch {
            setPhase("queued");
          }
        },
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload could not start.");
      setPhase("error");
    }
  }

  function reset() {
    setFile(null);
    setPreflight(null);
    setProgress(null);
    setPhase("idle");
    handleRef.current = null;
    if (inputRef.current) inputRef.current.value = "";
  }

  async function abort() {
    await handleRef.current?.abort();
    reset();
  }

  const busy = phase === "uploading" || phase === "paused" || phase === "finalizing";

  return (
    <div>
      {resumable.length > 0 && phase === "idle" && (
        <Surface className="mb-4">
          <p className="text-[13px] font-medium mb-2" style={{ color: "var(--text-primary)" }}>
            Unfinished uploads
          </p>
          <div className="divide-y" style={{ borderColor: "var(--separator)" }}>
            {resumable.map((u) => (
              <div key={u.video_id} className="flex items-center justify-between gap-3 py-2">
                <div className="min-w-0">
                  <p className="text-[13px] truncate" style={{ color: "var(--text-primary)" }}>
                    {u.original_filename}
                  </p>
                  <p className="tnum text-[12px]" style={{ color: "var(--text-tertiary)" }}>
                    {formatBytes(u.received_size_bytes)} of {formatBytes(u.expected_size_bytes)} sent
                  </p>
                </div>
                <Button
                  variant="ghost"
                  onClick={async () => {
                    await cancelUpload(u.video_id);
                    setResumable((prev) => prev.filter((x) => x.video_id !== u.video_id));
                  }}
                >
                  Discard
                </Button>
              </div>
            ))}
          </div>
          <p className="text-[12px] mt-2" style={{ color: "var(--text-tertiary)" }}>
            Choose the same file below to resume where it left off.
          </p>
        </Surface>
      )}

      <div className="flex flex-wrap gap-3 mb-4">
        <select
          value={matchFormat}
          onChange={(e) => setMatchFormat(e.target.value)}
          disabled={busy}
          aria-label="Match format"
          className="rounded-[var(--radius-sm)] px-3 text-[14px] disabled:opacity-50"
          style={{
            border: "1px solid var(--separator)", background: "var(--surface-sunken)",
            color: "var(--text-primary)", minHeight: 44,
          }}
        >
          <option value="singles">Singles</option>
          <option value="doubles">Doubles</option>
          <option value="unknown">Not sure</option>
        </select>
        <input
          placeholder="Opponent name (optional)"
          value={opponentName}
          onChange={(e) => setOpponentName(e.target.value)}
          disabled={busy}
          aria-label="Opponent name"
          className="rounded-[var(--radius-sm)] px-3 text-[14px] flex-1 min-w-[180px] disabled:opacity-50"
          style={{
            border: "1px solid var(--separator)", background: "var(--surface-sunken)",
            color: "var(--text-primary)", minHeight: 44,
          }}
        />
      </div>

      {phase === "idle" || phase === "selected" ? (
        <div
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            const dropped = e.dataTransfer.files?.[0];
            if (dropped) void pickFile(dropped);
          }}
          className="rounded-[var(--radius-lg)] p-6 text-center transition-colors"
          style={{
            border: `1px dashed ${dragging ? "var(--accent)" : "var(--separator-strong)"}`,
            background: dragging ? "var(--accent-soft)" : "var(--surface-sunken)",
          }}
        >
          <input
            ref={inputRef}
            type="file"
            accept="video/mp4,video/quicktime,video/x-msvideo,video/webm,.mp4,.mov,.m4v,.avi,.webm"
            className="hidden"
            onChange={(e) => e.target.files?.[0] && void pickFile(e.target.files[0])}
          />

          {!file ? (
            <>
              <p className="text-[15px] font-medium" style={{ color: "var(--text-primary)" }}>
                Drop a match recording here
              </p>
              <p className="text-[13px] mt-1 mb-4" style={{ color: "var(--text-secondary)" }}>
                Uploads go straight to secure storage and resume if your connection drops.
              </p>
              <Button variant="primary" onClick={() => inputRef.current?.click()}>
                Choose video file
              </Button>
            </>
          ) : (
            <div className="text-left">
              <FileSummary file={file} preflight={preflight} />
              <div className="flex gap-2 mt-4">
                <Button variant="primary" onClick={begin}>Start upload</Button>
                <Button variant="ghost" onClick={reset}>Choose another</Button>
              </div>
            </div>
          )}
        </div>
      ) : (
        <Surface>
          <UploadStatus
            phase={phase}
            file={file}
            progress={progress}
            error={error}
            onPause={() => { handleRef.current?.pause(); setPhase("paused"); }}
            onResume={() => { handleRef.current?.resume(); setPhase("uploading"); }}
            onRetry={() => { setError(null); void begin(); }}
            onCancel={abort}
          />
        </Surface>
      )}

      <p className="text-[12px] mt-3" style={{ color: "var(--text-tertiary)" }}>
        MP4, MOV, M4V, AVI or WebM. Large files are fine — ShuttleSense optimizes the
        recording after upload, so there's no need to compress it first.
      </p>
    </div>
  );
}

function FileSummary({ file, preflight }: { file: File; preflight: Preflight | null }) {
  return (
    <div>
      <p className="text-[15px] font-medium truncate" style={{ color: "var(--text-primary)" }}>
        {file.name}
      </p>
      <dl className="mt-2 grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-2">
        <Fact label="Size" value={formatBytes(file.size)} />
        <Fact label="Duration" value={formatClipDuration(preflight?.durationSeconds ?? null)} />
        <Fact label="Resolution" value={preflight?.resolutionLabel ?? "—"} />
        <Fact label="Format" value={(file.name.split(".").pop() || "?").toUpperCase()} />
      </dl>
      {preflight?.warnings.map((w) => (
        <p key={w} className="text-[12px] mt-2" style={{ color: "var(--warning)" }}>{w}</p>
      ))}
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[12px]" style={{ color: "var(--text-tertiary)" }}>{label}</dt>
      <dd className="tnum text-[14px] font-medium" style={{ color: "var(--text-primary)" }}>{value}</dd>
    </div>
  );
}

function UploadStatus({
  phase, file, progress, error, onPause, onResume, onRetry, onCancel,
}: {
  phase: Phase;
  file: File | null;
  progress: UploadProgress | null;
  error: string | null;
  onPause: () => void;
  onResume: () => void;
  onRetry: () => void;
  onCancel: () => void;
}) {
  const percent = progress?.percent ?? 0;

  // Phrasing matters here: at 100% the bytes have arrived but the server is
  // still verifying, so the label changes rather than leaving "Uploading" on
  // screen through a step the user is not waiting on any more.
  const heading =
    phase === "error" ? "Upload interrupted"
    : phase === "paused" ? "Upload paused"
    : phase === "finalizing" ? "Checking the upload"
    : phase === "queued" ? "Queued for analysis"
    : "Uploading";

  return (
    <div>
      <div className="flex items-baseline justify-between gap-4">
        <div className="min-w-0">
          <p className="text-[15px] font-medium" style={{ color: "var(--text-primary)" }}>{heading}</p>
          {file && (
            <p className="text-[13px] truncate mt-0.5" style={{ color: "var(--text-secondary)" }}>
              {file.name}
            </p>
          )}
        </div>
        {phase !== "finalizing" && phase !== "queued" && (
          <span className="tnum text-[24px] font-semibold" style={{ color: "var(--accent)" }}>
            {percent.toFixed(0)}%
          </span>
        )}
      </div>

      <div
        className="h-1.5 rounded-[var(--radius-full)] overflow-hidden mt-3"
        style={{ background: "var(--surface-sunken)" }}
        role="progressbar"
        aria-valuenow={Math.round(percent)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Upload progress"
      >
        <div
          className="h-full transition-[width] duration-300"
          style={{
            width: `${phase === "finalizing" || phase === "queued" ? 100 : percent}%`,
            background: phase === "error" ? "var(--negative)" : "var(--accent)",
          }}
        />
      </div>

      {progress && phase !== "queued" && (
        <p className="tnum text-[12px] mt-2" style={{ color: "var(--text-tertiary)" }}>
          {formatBytes(progress.bytesUploaded)} of {formatBytes(progress.bytesTotal)}
          {progress.bytesPerSecond !== null && (
            <> · {formatBytes(progress.bytesPerSecond)}/s · {formatDuration(progress.secondsRemaining)} left</>
          )}
        </p>
      )}

      {error && (
        <p className="text-[13px] mt-3" style={{ color: "var(--negative)" }} role="alert">{error}</p>
      )}

      <div className="flex gap-2 mt-4">
        {phase === "uploading" && <Button variant="ghost" onClick={onPause}>Pause</Button>}
        {phase === "paused" && <Button variant="primary" onClick={onResume}>Resume</Button>}
        {phase === "error" && <Button variant="primary" onClick={onRetry}>Retry</Button>}
        {phase !== "queued" && phase !== "finalizing" && (
          <Button variant="ghost" onClick={onCancel}>Cancel</Button>
        )}
      </div>

      {phase === "uploading" && (
        <p className="text-[12px] mt-3" style={{ color: "var(--text-tertiary)" }}>
          You can leave this page once the upload finishes — analysis continues on our servers.
        </p>
      )}
    </div>
  );
}
