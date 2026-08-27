/* ==========================================================================
   Client-side preflight.

   Deliberately lightweight. The browser reads what a <video> element will tell
   it for free — duration, dimensions — and nothing more. It does NOT transcode.

   Heavy in-browser ffmpeg.wasm compression was considered and rejected as the
   primary architecture: it pins a phone's CPU for minutes on a 4 GB file,
   allocates the file in WASM memory, drains the battery, thermally throttles
   the device, and produces nothing until it finishes — so a user who closes
   the tab has uploaded zero bytes. Server-side normalization gives the same
   output, starts uploading immediately, and cannot be killed by a tab close.

   What this DOES buy is telling the user what they picked before a long
   upload starts.
   ========================================================================== */

export interface Preflight {
  sizeBytes: number;
  durationSeconds: number | null;
  width: number | null;
  height: number | null;
  /** What the OS guessed. Not authoritative — ffprobe decides server-side. */
  declaredType: string;
  resolutionLabel: string | null;
  warnings: string[];
}

const READABLE_EXTENSIONS = /\.(mp4|mov|m4v|avi|webm|mkv)$/i;

function resolutionLabel(w: number | null, h: number | null): string | null {
  if (!w || !h) return null;
  const shortest = Math.min(w, h);
  if (shortest >= 2000) return "4K";
  if (shortest >= 1400) return "1440p";
  if (shortest >= 1000) return "1080p";
  if (shortest >= 700) return "720p";
  if (shortest >= 460) return "480p";
  return `${w}x${h}`;
}

/** Read metadata from the file without decoding it. Resolves with nulls
 *  rather than rejecting: a container the browser cannot preview may still be
 *  perfectly analysable server-side, and refusing it here would be wrong. */
export function inspect(file: File): Promise<Preflight> {
  return new Promise((resolve) => {
    const base: Preflight = {
      sizeBytes: file.size,
      durationSeconds: null,
      width: null,
      height: null,
      declaredType: file.type || "unknown",
      resolutionLabel: null,
      warnings: [],
    };

    if (!READABLE_EXTENSIONS.test(file.name) && !file.type.startsWith("video/")) {
      base.warnings.push("This doesn't look like a video file.");
    }

    const url = URL.createObjectURL(file);
    const video = document.createElement("video");
    video.preload = "metadata";
    let settled = false;

    const finish = (result: Preflight) => {
      if (settled) return;
      settled = true;
      URL.revokeObjectURL(url);
      resolve(result);
    };

    video.onloadedmetadata = () => {
      const width = video.videoWidth || null;
      const height = video.videoHeight || null;
      const duration = Number.isFinite(video.duration) ? video.duration : null;
      const warnings = [...base.warnings];

      if (duration !== null && duration > 90 * 60) {
        warnings.push("This recording is very long. Trimming to the games you want reviewed gives faster, sharper analysis.");
      }
      if (width && height && Math.min(width, height) < 480) {
        warnings.push("Low resolution footage makes shuttle tracking unreliable.");
      }
      finish({
        ...base, width, height, durationSeconds: duration,
        resolutionLabel: resolutionLabel(width, height), warnings,
      });
    };

    // A container Safari or Chrome cannot preview is not a rejection: ffprobe
    // is the authority and it runs server-side after the upload.
    video.onerror = () => finish(base);
    // Some containers never fire either event. Don't hang the picker.
    setTimeout(() => finish(base), 4000);

    video.src = url;
  });
}

export function formatClipDuration(seconds: number | null): string {
  if (seconds === null) return "—";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return h > 0
    ? `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`
    : `${m}:${s.toString().padStart(2, "0")}`;
}
