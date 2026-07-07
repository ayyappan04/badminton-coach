# Computer-Vision Pipeline Design

The pipeline is a sequence of independent stages, each with a typed input/output contract, implemented in `backend/app/services/cv_pipeline/`. Every stage attaches a confidence score and, when relevant, a list of limitation tags (`low_frame_rate`, `motion_blur`, `poor_lighting`, `camera_occlusion`, `single_camera_no_depth`, `court_partially_visible`).

```
video file
   │
   ▼
1. Frame extraction ─────────────► frames[] at analysis fps (default 10 fps sampling
                                    for detection stages, native fps for shuttle/pose
                                    where motion resolution matters)
   │
   ▼
2. Court detection & calibration ─► court corner estimate, homography (pixel→court-meters),
                                    confidence. Falls back to user-assisted 4-point
                                    calibration when auto-detection confidence < threshold.
   │
   ▼
3. Player detection & tracking ───► per-frame bounding boxes + track IDs, using
                                    background-subtraction-assisted HOG detection +
                                    IOU/centroid tracker (Phase 2: swap in YOLOv8).
                                    User confirms "which track is me" via
                                    /tracked-persons/claim.
   │
   ▼
4. Pose estimation ───────────────► 33-point body landmarks per tracked person per frame
                                    (MediaPipe Pose, run per-crop). Confidence from
                                    landmark visibility scores.
   │
   ▼
5. Shuttle detection & trajectory ► frame-differencing + small-fast-blob heuristic;
                                    explicitly low default confidence. This is the
                                    single hardest CV problem here (tiny, fast, motion-
                                    blurred object) — flagged as experimental until a
                                    trained detector replaces it (Phase 2/3).
   │
   ▼
6. Court-coordinate transform ────► maps player centroids + shuttle positions from
                                    pixel space into real-world court meters using the
                                    homography from stage 2. Powers heatmaps, movement
                                    trails, coverage stats.
   │
   ▼
7. Rally segmentation ────────────► splits the match into rallies using motion-energy
                                    troughs (long stillness = between-rally) and serve-
                                    position heuristics.
   │
   ▼
8. Shot recognition (heuristic) ──► per detected swing (wrist acceleration peak near
                                    shuttle proximity), classifies contact height
                                    (overhead/underhand from wrist-vs-shoulder y),
                                    side (forehand/backhand from wrist-vs-torso x
                                    relative to dominant hand), and a coarse shot-type
                                    guess from trajectory shape + contact height.
                                    Phase 2 upgrades this to a trained classifier.
   │
   ▼
9. Biomechanical feature estimation ► joint angles (elbow, knee, hip/shoulder rotation
                                    proxy from landmark vectors), stance classification,
                                    approximate center of mass (weighted landmark
                                    centroid), stability score (base-of-support vs.
                                    COM projection).
   │
   ▼
10. Tactical pattern analysis ────► court occupancy heatmap, dead-zone detection,
                                    recovery-time-to-center, formation classification
                                    in doubles (front-back vs side-by-side via
                                    partner relative position).
   │
   ▼
11. Overlay rendering ────────────► per-frame overlay manifest (JSON, not baked into
                                    video) consumed by the frontend canvas layer, so
                                    users can toggle individual overlays (skeleton,
                                    court lines, shuttle trail, heatmap).
```

## Handling poor-quality video

- If fewer than N court-line segments are detected with sufficient confidence, the pipeline requests **user-assisted calibration**: show a frame, let the user drag the 4 court corners.
- If a tracked person's bounding box confidence drops below threshold for > X consecutive frames (occlusion), the track is interpolated for short gaps and marked `occluded` for longer ones; downstream stability/stance scores are suppressed (not guessed) during occluded spans.
- If overall frame rate < 24fps, shuttle-speed and contact-timing outputs are still produced but flagged `low_frame_rate` with reduced confidence, since fast shots (smash) can travel multiple meters between frames.
- If resolution is below a threshold (e.g. shuttle bounding box would be < 3px), shuttle detection is skipped entirely and the UI explains why, rather than emitting noise.

## Why classical CV + MediaPipe for the MVP, not end-to-end deep learning

Pose estimation (MediaPipe) is a mature, offline, pretrained solution — safe to depend on immediately. Court-line detection via Hough transforms is deterministic, explainable, and fails gracefully into manual calibration. Player detection uses OpenCV's built-in HOG detector to avoid pulling in GPU-oriented deep learning dependencies for the MVP; this is the first component slated for replacement (YOLOv8/RT-DETR) once the product needs better multi-player tracking density (e.g. doubles with 4 players and frequent occlusion) — see ROADMAP.md.

## Confidence scoring approach

Each stage emits `confidence ∈ [0,1]` computed from stage-appropriate signals (e.g. Hough line inlier ratio for court detection, MediaPipe visibility scores for pose, tracker IOU continuity for tracking, blob size/speed plausibility for shuttle). Coaching insights inherit the minimum confidence of the CV signals they depend on, so a shot-technique comment never reads as more certain than its underlying pose/shuttle data.
