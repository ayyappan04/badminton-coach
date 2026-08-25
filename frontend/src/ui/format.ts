/** Number and unit formatting. Consistent precision is part of looking
 *  precise — `1.42s`, never `1.42381291 seconds`. */

export function formatScore(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return String(Math.round(v));
}

export function formatPercent(v: number | null | undefined, decimals = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v.toFixed(decimals)}%`;
}

/** Accepts a 0–1 ratio and renders it as a whole percentage. */
export function formatRatioPercent(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${Math.round(v * 100)}%`;
}

export function formatSeconds(v: number | null | undefined, decimals = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v.toFixed(decimals)}s`;
}

export function formatCount(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return String(v);
}

/** Video timestamp: 0:42, 1:18, 12:05 */
export function formatTimestamp(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

export function titleCase(s: string | null | undefined): string {
  if (!s) return "—";
  return s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

/** Human-readable label for a pipeline limitation tag. */
export function limitationLabel(tag: string): string {
  const map: Record<string, string> = {
    low_video_quality: "Low recording quality",
    camera_cuts_detected: "Scene cuts detected",
    low_frame_rate_source: "Low frame rate",
    no_players_detected: "No players detected",
    no_pose_landmarks_detected: "Body tracking unavailable",
    shuttle_not_reliably_detected: "Shuttle not reliably tracked",
    no_rallies_segmented: "No rallies detected",
    court_partially_visible: "Court only partly visible",
    auto_detection_failed: "Court detection failed",
    needs_user_calibration: "Needs manual court calibration",
    low_confidence_auto_detection: "Low-confidence court detection",
    no_court_transform_available_for_tactics: "Court mapping unavailable",
    single_camera_no_depth: "Single camera — no depth",
    "2d_projection_estimate": "2D estimate",
    contact_frame_approximate: "Approximate contact frame",
    contact_timing_approximate: "Approximate contact timing",
    court_calibration_approximate: "Approximate court calibration",
    doubles_tracking_prone_to_occlusion: "Doubles tracking — occlusion prone",
    shot_type_heuristic_not_trained_classifier: "Shot types are heuristic",
    sparse_sampling_long_video: "Sampled sparsely (long video)",
    analysis_truncated_memory_budget: "Analysis truncated (length)",
    video_too_long: "Video too long",
    video_unusable_for_analysis: "Unusable for analysis",
  };
  return map[tag] ?? titleCase(tag);
}

/* --- Semantic helpers for data display ---------------------------------- */

export type Sentiment = "positive" | "negative" | "neutral";

/** Direction and sentiment are separate concerns: a recovery time going DOWN
 *  is an improvement, an error count going UP is not. */
export function deltaSentiment(change: number, lowerIsBetter = false): Sentiment {
  if (change === 0) return "neutral";
  const improving = lowerIsBetter ? change < 0 : change > 0;
  return improving ? "positive" : "negative";
}

export function confidenceTone(ratio: number): "high" | "medium" | "low" {
  if (ratio >= 0.7) return "high";
  if (ratio >= 0.45) return "medium";
  return "low";
}
