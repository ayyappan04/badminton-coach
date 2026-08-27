import * as tus from "tus-js-client";
import { api, getToken } from "../api/client";
import { SUPABASE_URL, currentAccessToken, supabaseEnabled } from "./supabase";

/* ==========================================================================
   Resumable direct-to-storage upload.

   The video bytes go browser -> object storage. They never pass through the
   application API, and on Vercel they never touch a serverless function: a
   4 GB match would exceed every request-body limit in that path and would be
   billed as compute for the privilege.

   Two transports behind one interface:
     tus  — Supabase Storage resumable uploads (production)
     put  — chunked PUT to the local dev API (STORAGE_BACKEND=local)

   Both support pause, resume, retry and cancel, so the UI has one set of
   controls rather than two code paths.
   ========================================================================== */

/** 6 MB. Supabase's resumable endpoint requires a fixed chunk size, and this
 *  is the size it documents. Smaller means more round trips on a fast link;
 *  larger means more to redo when a train goes into a tunnel. */
const TUS_CHUNK_BYTES = 6 * 1024 * 1024;
const PUT_CHUNK_BYTES = 8 * 1024 * 1024;

export interface UploadTicket {
  video_id: string;
  bucket: string;
  object_path: string;
  upload_method: "tus" | "put";
  endpoint: string;
  expires_at: string | null;
  max_bytes: number;
  headers: Record<string, string>;
  storage_backend: string;
}

export interface UploadProgress {
  bytesUploaded: number;
  bytesTotal: number;
  percent: number;
  /** Bytes/second over a trailing window, or null until it can be measured
   *  honestly. A fabricated "2 minutes remaining" is worse than none. */
  bytesPerSecond: number | null;
  secondsRemaining: number | null;
}

export interface UploadHandle {
  videoId: string;
  pause: () => void;
  resume: () => void;
  abort: () => Promise<void>;
}

export interface StartUploadOptions {
  file: File;
  matchFormat: string;
  opponentName?: string;
  recordedAt?: string;
  onProgress?: (p: UploadProgress) => void;
  onTicket?: (t: UploadTicket) => void;
  onSuccess?: (videoId: string) => void;
  onError?: (message: string, retryable: boolean) => void;
}

/* --- speed estimation ------------------------------------------------------
   A trailing window rather than a cumulative average: on a mobile connection
   the average over the whole upload describes a network condition that stopped
   applying ten minutes ago.
   -------------------------------------------------------------------------- */
class RateEstimator {
  private samples: { t: number; bytes: number }[] = [];
  private readonly windowMs = 12_000;

  push(bytes: number): void {
    const now = Date.now();
    this.samples.push({ t: now, bytes });
    while (this.samples.length > 1 && now - this.samples[0].t > this.windowMs) {
      this.samples.shift();
    }
  }

  bytesPerSecond(): number | null {
    if (this.samples.length < 2) return null;
    const first = this.samples[0];
    const last = this.samples[this.samples.length - 1];
    const seconds = (last.t - first.t) / 1000;
    // Under three seconds of evidence, any number is noise.
    if (seconds < 3) return null;
    const delta = last.bytes - first.bytes;
    return delta > 0 ? delta / seconds : null;
  }
}

function progressOf(uploaded: number, total: number, rate: RateEstimator): UploadProgress {
  rate.push(uploaded);
  const bps = rate.bytesPerSecond();
  return {
    bytesUploaded: uploaded,
    bytesTotal: total,
    percent: total > 0 ? Math.min(100, (uploaded / total) * 100) : 0,
    bytesPerSecond: bps,
    secondsRemaining: bps && bps > 0 ? Math.max(0, (total - uploaded) / bps) : null,
  };
}

/** Ask the control plane to allocate a path and record intent. Cheap: no
 *  bytes move here. */
export async function requestTicket(opts: {
  file: File; matchFormat: string; opponentName?: string; recordedAt?: string;
}): Promise<UploadTicket> {
  return api.post<UploadTicket>("/videos/uploads", {
    filename: opts.file.name,
    content_type: opts.file.type || "video/mp4",
    size_bytes: opts.file.size,
    match_format: opts.matchFormat,
    opponent_name: opts.opponentName || null,
    recorded_at: opts.recordedAt || null,
  });
}

/** Verify server-side that the object landed intact, then queue analysis. */
export async function completeUpload(videoId: string): Promise<void> {
  await api.post(`/videos/uploads/${videoId}/complete`);
}

export async function cancelUpload(videoId: string): Promise<void> {
  try {
    await api.post(`/videos/uploads/${videoId}/cancel`);
  } catch {
    // A cancel that fails is not worth surfacing: the session expires anyway.
  }
}

export async function startUpload(opts: StartUploadOptions): Promise<UploadHandle> {
  const ticket = await requestTicket(opts);
  opts.onTicket?.(ticket);

  if (ticket.upload_method === "tus" && supabaseEnabled) {
    return startTusUpload(ticket, opts);
  }
  return startPutUpload(ticket, opts);
}

/* --- Supabase resumable (TUS) --------------------------------------------- */

async function startTusUpload(ticket: UploadTicket, opts: StartUploadOptions): Promise<UploadHandle> {
  const accessToken = await currentAccessToken();
  if (!accessToken) throw new Error("Not signed in.");

  const rate = new RateEstimator();
  let upload: tus.Upload | null = null;

  await new Promise<void>((resolve, reject) => {
    upload = new tus.Upload(opts.file, {
      endpoint: ticket.endpoint || `${SUPABASE_URL}/storage/v1/upload/resumable`,
      // The browser authenticates with its OWN Supabase session. The API never
      // hands out a storage credential; Storage RLS checks that the first path
      // segment is this user's id, so a tampered objectName is refused by
      // Postgres rather than trusted by us.
      headers: { authorization: `Bearer ${accessToken}`, ...ticket.headers },
      uploadDataDuringCreation: true,
      removeFingerprintOnSuccess: true,
      chunkSize: TUS_CHUNK_BYTES,
      // Exponential backoff. A flaky cellular link should recover on its own
      // rather than making the user start a 4 GB upload again.
      retryDelays: [0, 1000, 3000, 6000, 12000, 24000],
      metadata: {
        bucketName: ticket.bucket,
        objectName: ticket.object_path,
        contentType: opts.file.type || "video/mp4",
        cacheControl: "3600",
      },
      onProgress: (uploaded, total) => opts.onProgress?.(progressOf(uploaded, total, rate)),
      onError: (error) => {
        const message = error instanceof Error ? error.message : String(error);
        opts.onError?.(friendlyUploadError(message), true);
        reject(error);
      },
      onSuccess: () => resolve(),
    });

    // Resume rather than restart when a previous attempt for this exact file
    // is still in flight — this is what survives a browser refresh.
    upload.findPreviousUploads().then((previous) => {
      if (previous.length > 0) upload!.resumeFromPreviousUpload(previous[0]);
      upload!.start();
    });
  });

  await completeUpload(ticket.video_id);
  opts.onSuccess?.(ticket.video_id);

  return {
    videoId: ticket.video_id,
    pause: () => upload?.abort(),
    resume: () => void upload?.start(),
    abort: async () => {
      await upload?.abort(true);
      await cancelUpload(ticket.video_id);
    },
  };
}

/* --- Local dev: chunked PUT ----------------------------------------------- */

async function startPutUpload(ticket: UploadTicket, opts: StartUploadOptions): Promise<UploadHandle> {
  const rate = new RateEstimator();
  const controller = new AbortController();
  let paused = false;
  let offset = 0;

  const run = async () => {
    const token = getToken();
    while (offset < opts.file.size) {
      if (paused) return;
      const end = Math.min(offset + PUT_CHUNK_BYTES, opts.file.size);
      const chunk = opts.file.slice(offset, end);
      const res = await fetch(`/api/v1${ticket.endpoint.replace("/api/v1", "")}`, {
        method: "PUT",
        signal: controller.signal,
        headers: {
          ...(token ? { authorization: `Bearer ${token}` } : {}),
          "content-type": "application/octet-stream",
          "content-range": `bytes ${offset}-${end - 1}/${opts.file.size}`,
        },
        body: chunk,
      });
      if (!res.ok) throw new Error(`Upload failed (${res.status})`);
      offset = end;
      opts.onProgress?.(progressOf(offset, opts.file.size, rate));
    }
    await completeUpload(ticket.video_id);
    opts.onSuccess?.(ticket.video_id);
  };

  const promise = run().catch((err) => {
    if (controller.signal.aborted) return;
    opts.onError?.(friendlyUploadError(err instanceof Error ? err.message : String(err)), true);
    throw err;
  });

  await promise;

  return {
    videoId: ticket.video_id,
    pause: () => { paused = true; },
    resume: () => { paused = false; void run(); },
    abort: async () => {
      controller.abort();
      await cancelUpload(ticket.video_id);
    },
  };
}

/* --- helpers -------------------------------------------------------------- */

function friendlyUploadError(raw: string): string {
  const lowered = raw.toLowerCase();
  if (lowered.includes("network") || lowered.includes("failed to fetch")) {
    return "The connection dropped. The upload will resume where it left off.";
  }
  if (lowered.includes("413") || lowered.includes("too large")) {
    return "That file is larger than the maximum upload size.";
  }
  if (lowered.includes("401") || lowered.includes("403")) {
    return "Your session expired. Sign in again to continue the upload.";
  }
  return "The upload was interrupted. You can retry without starting over.";
}

export function formatBytes(bytes: number): string {
  if (!bytes || bytes < 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
  const value = bytes / Math.pow(1024, i);
  return `${value.toFixed(value >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return "—";
  if (seconds < 60) return `${Math.ceil(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  if (m < 60) return `${m}m ${s.toString().padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${(m % 60).toString().padStart(2, "0")}m`;
}
