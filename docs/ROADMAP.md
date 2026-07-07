# Phased Product Roadmap

## Phase 0 — MVP (this repo's working code)

Goal: a player can upload a match and get real, honestly-scoped coaching value.

1. Upload a video; store it; basic validation (format, duration, resolution).
2. Detect the court (auto Hough-line estimate; user-assisted 4-point calibration fallback).
3. Let the user identify which tracked person is them.
4. Track players (classical detector + tracker) across the match.
5. Detect rallies and basic shot events (heuristic: swing timing, contact height, trajectory shape).
6. Generate court-positioning and movement insights (heatmap, coverage, recovery timing).
7. Present coaching insights as clips linked to timestamps, each with confidence + limitations.
8. Show technique guidance via a structured "Correct Form" reference (phase breakdown + common mistakes) and matched drills.
9. Build a historical player profile across multiple uploads (radar scores, play-style evidence, trend).

Explicitly deferred out of Phase 0: racket tracking, precise shuttle physics, contact-angle estimation, true center-of-mass biomechanics, and 3D/animated technique simulation — all present as simplified, clearly-labeled approximations for now.

## Phase 1 — Reliability & UX hardening

- Improve court calibration UX (drag-to-correct corners, live preview of homography).
- WebSocket-based processing progress instead of polling.
- Better failure messaging for poor-quality video (resolution/frame-rate/lighting checks before processing starts, with specific guidance: "record from an elevated angle if possible," "increase lighting," etc.).
- Community MVP: friends, sharing scopes, basic practice planning.

## Phase 2 — Stronger detection models

- Replace HOG-based player detection/tracking with a modern detector (YOLOv8/RT-DETR) + a proper multi-object tracker (ByteTrack/DeepSORT) for robust doubles tracking through occlusion.
- Trained shuttle detector (small-object detection model, e.g. a YOLO variant fine-tuned on annotated badminton footage) to replace the motion-heuristic shuttle tracker; large accuracy/confidence jump expected here.
- Racket detection/tracking (grip region, racket head, orientation) via a fine-tuned object detector.
- Trained shot-type classifier (temporal model over pose + shuttle trajectory windows) to replace today's rule-based shot recognition.
- Begin building the licensed/consented training-data pipeline described in PRIVACY_AND_CONSENT.md to support the above training work.

## Phase 3 — Community depth & advanced visuals (shipped in this repo)

Delivered:
- Advanced doubles rotation analysis: formation timeline, rotation timing
  after attack transitions, missed-rotation detection, partner spacing /
  overlap / open-middle-channel findings — surfaced as an analytics block
  with per-finding suggestions.
- Comparison Studio v3: smoothly interpolated reference animation with a
  racket-path arc, contact-point marker, footwork-path inset, and the user's
  own racket-hand (wrist-estimate) path drawn over their clip from stored
  pose data.
- Team/coach tools: club detail pages with a team dashboard that shows only
  members who opted in via the new per-metric consent flag
  (share_progress_with_club, off by default).
- Shared clips: one-click clip sharing from any coaching insight (uses the
  account's default sharing scope), playable clip list in Community.
- Shuttle trajectory refinement: per-segment velocity-outlier rejection and
  median smoothing (still experimental; confidence capped at 0.5).
- Reliability: overlay manifests and heatmaps rebuild from persisted rows,
  so replay visuals survive server restarts.

Still model/asset-gated (unchanged honesty boundary):
- True racket detection (position/angle/head speed) — needs a fine-tuned detector.
- Multi-camera or monocular-depth 3D pose lifting; contact-angle / shuttle-spin estimation.
- Full 3D skeletal animation for the simulator (current reference is a 2D animated figure).

## Phase 4 — Scale & ecosystem

- Full community/social feature set: clubs, group training, challenges, shared milestone tracking.
- Coach-facing view: a human coach can review a student's AI-generated analysis and annotate/override insights.
- Public API for club/federation integrations (with the same consent/licensing safeguards extended to any bulk footage they provide).
