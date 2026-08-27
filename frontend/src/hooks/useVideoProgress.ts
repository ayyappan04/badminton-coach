import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { supabase, supabaseEnabled } from "../lib/supabase";
import type { Video } from "../types";

/* ==========================================================================
   Live processing progress.

   Realtime when it is available, polling underneath it always.

   The polling is not a fallback that gets switched off when the websocket
   connects — it stays on at a slow cadence. Correctness must not depend on a
   socket staying up: Postgres holds the truth, and a missed event should cost
   a few seconds of staleness, never a video that appears stuck forever.
   ========================================================================== */

/** Fast while a socket is absent, slow while one is delivering. */
const POLL_ACTIVE_MS = 2500;
const POLL_BACKUP_MS = 15000;

const IN_FLIGHT = new Set([
  "created", "uploading", "uploaded", "validating", "queued", "normalizing", "processing",
]);

export function isInFlight(status: string | null | undefined): boolean {
  return !!status && IN_FLIGHT.has(status);
}

export function useVideoProgress(videos: Video[], onUpdate: () => void) {
  const [realtimeConnected, setRealtimeConnected] = useState(false);
  const onUpdateRef = useRef(onUpdate);
  onUpdateRef.current = onUpdate;

  const anyActive = videos.some((v) => isInFlight(v.status));

  /* --- Realtime --------------------------------------------------------- */
  useEffect(() => {
    if (!supabaseEnabled || !supabase || !anyActive) return;

    // RLS applies to Realtime, so this subscription can only ever deliver rows
    // the user could already SELECT. No extra filtering is needed here, and
    // adding some would give a false impression of where the boundary is.
    const channel = supabase
      .channel("video-progress")
      .on("postgres_changes",
        { event: "UPDATE", schema: "public", table: "videos" },
        () => onUpdateRef.current())
      .on("postgres_changes",
        { event: "INSERT", schema: "public", table: "processing_events" },
        () => onUpdateRef.current())
      .subscribe((status) => setRealtimeConnected(status === "SUBSCRIBED"));

    return () => {
      setRealtimeConnected(false);
      void supabase?.removeChannel(channel);
    };
  }, [anyActive]);

  /* --- Polling ---------------------------------------------------------- */
  useEffect(() => {
    if (!anyActive) return;
    const interval = realtimeConnected ? POLL_BACKUP_MS : POLL_ACTIVE_MS;
    const timer = setInterval(() => onUpdateRef.current(), interval);
    return () => clearInterval(timer);
  }, [anyActive, realtimeConnected]);

  return { realtimeConnected, anyActive };
}

/** Processing history for one video: the stage-level trail the worker wrote. */
export function useProcessingEvents(videoId: string | null, enabled: boolean) {
  const [events, setEvents] = useState<
    { created_at: string; event_type: string; stage: string | null; message: string | null }[]
  >([]);

  useEffect(() => {
    if (!videoId || !enabled) {
      setEvents([]);
      return;
    }
    let cancelled = false;
    api.get<typeof events>(`/videos/${videoId}/events`)
      .then((rows) => { if (!cancelled) setEvents(rows); })
      .catch(() => { if (!cancelled) setEvents([]); });
    return () => { cancelled = true; };
  }, [videoId, enabled]);

  return events;
}
