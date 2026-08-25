# Real footage test results

Measured by `python -m tests.run_real_footage_matrix` against pipeline 2.0.0.
Raw data: `docs/evidence/real-footage-matrix.json`.
Sources and attribution: `docs/evidence/real-footage-attribution.md`.

**Footage:** six openly-licensed clips (CC0 / public domain / CC BY / CC BY-SA)
from Wikimedia Commons — 13.6 minutes total, from 320×240 school play up to
1920×1080 elite tour broadcast. **No BWF or other rights-reserved footage was
downloaded**; see `BWF_MANUAL_TEST_PROTOCOL.md` for how that is covered.

---

## Results

| Clip | Resolution | Dur | Quality | Court conf | Tracks | Pose coverage | Pose conf | Shots | Rallies |
|---|---|---|---|---|---|---|---|---|---|
| `school_training` | 320×240 | 60 s | 60 | 0.15 → fallback | 27 | 79.9% | 0.72 | 0 | 0 |
| `club_competition` | 848×464 | 26 s | 82 | 0.79 | 11 | 85.8% | 0.84 | 12 | 3 |
| `competition_long` | 848×464 | 97 s | 74 | 0.72 | 46 | 88.0% | 0.85 | 73 | 11 |
| `championship_point` | 1920×1080 | 32 s | 75 | 0.71 | 27 | 84.7% | 0.84 | 71 | 2 |
| `demonstration` | 720×576 | 96 s | 43 | 0.15 → fallback | 65 | 28.2% | 0.74 | 38 | 8 |
| `elite_broadcast` | 1920×1080 | 506 s | 81 | **0.89** | 23 | 75.8% | 0.85 | 20 | 13 |

---

## What this validates (and what it breaks)

### ✅ Pose estimation works on real footage — newly validated

**76–88% coverage with 0.72–0.85 mean confidence** across five of six clips.
This was previously **unmeasurable**: synthetic clips of coloured rectangles
produced zero MediaPipe landmarks, so the earlier report scored pose as "not
scored". It now has real numbers.

The exception is `demonstration` (28.2%) — archival footage that the quality
gate independently scored **43/100**, its lowest. Poor pose coverage on
low-quality footage is correct behaviour, and the two signals agree.

### ✅ Court detection is strongest on broadcast footage — 0.89

Counter-intuitive but explicable: broadcast cameras are elevated behind the
baseline with the full court framed, which is exactly the geometry the
line-family quad fit wants. The two clips where it fell back to
`needs_user_calibration` (0.15) were 320×240 school footage and archival
`demonstration` — both correctly identified as unusable for calibration
rather than fitted with invented geometry.

### ❌ Track fragmentation is severe — quantified

**11 to 65 tracks for videos containing 2–4 players.** That is 5–20×
over-segmentation: player identities break constantly and are re-issued as new
tracks. This is the same weakness the synthetic occlusion scenario exposed
(0 tracks), now measured on real bodies, and it is the strongest evidence yet
for replacing the classical HOG detector (`NEXT_STEPS.md` H2).

`track_persistence` (0.58–0.97) does *not* capture this, because it measures
the length of the top four tracks relative to the longest — it looks healthy
even when 60 spurious tracks exist alongside them. **That metric needs
replacing with a track-count-vs-expected-players ratio.**

### ❌ Shot recognition emits physically impossible rates — new finding

Shots per minute:

| Clip | Shots/min | Plausible? |
|---|---|---|
| `championship_point` | **131.1** | No — exceeds ~60/min ceiling of one shot per second |
| `competition_long` | 45.2 | Doubtful for continuous play |
| `demonstration` | 23.8 | Doubtful |
| `club_competition` | 28.1 | Doubtful |
| `elite_broadcast` | 2.4 | Suspiciously low (see sampling note) |

A badminton rally cannot exceed roughly one shot per second per player, so
131 shots/min is impossible. The cause is mechanical: the detector fires on
wrist-speed peaks *per track*, and with 27 fragmented tracks the same physical
swing is counted many times. **Shot counts are currently unusable as
statistics**, which also undermines every downstream figure derived from them
(shot mix, patterns, intent ratios).

This is a genuine regression in confidence versus the earlier report, which
could not measure it.

### ⚠️ Shot counts are not comparable across videos

`elite_broadcast` reports only 2.4 shots/min — not because it is accurate, but
because the new memory budget dropped it to 0.5 fps sampling, so most swings
are never seen. Sampling rate silently changes the statistic. Any cross-match
comparison (the Compare feature) is therefore **invalid between videos
analysed at different sample rates** until shot detection is normalised.

### ❌ Shuttle detector false positives confirmed at scale

**13,205 "shuttle points" on the 8.4-minute broadcast** and 2,644 on a
97-second clip. Confidence is capped at 0.5 and the UI labels it experimental,
but this is noise at a volume that could mislead. Reinforces `NEXT_STEPS.md` H4.

### ✅ Limitation flags behave correctly

Every degradation was surfaced, including the two new memory flags:

```
school_training     camera_cuts_detected, auto_detection_failed,
                    needs_user_calibration, shuttle_not_reliably_detected,
                    no_rallies_segmented
club_competition    (none — clean footage)
competition_long    court_partially_visible
championship_point  camera_cuts_detected, sparse_sampling_long_video
demonstration       low_video_quality, camera_cuts_detected,
                    sparse_sampling_long_video, analysis_truncated_memory_budget,
                    auto_detection_failed, needs_user_calibration
elite_broadcast     camera_cuts_detected, sparse_sampling_long_video,
                    analysis_truncated_memory_budget
```

The app does not silently degrade — it says what it could not do.

---

## Two crashes this testing found and fixed

Both were invisible to the synthetic matrix because every synthetic clip is
under 12 seconds. The 8.4-minute 1080p broadcast clip SIGKILLed the worker
(exit 137) on first run.

| Bug | Cost | Fix |
|---|---|---|
| `shuttle_detection` materialised every **native-fps** frame (`list(frames_native)`) | 15,120 frames × 6.2 MB ≈ **94 GB** | Streamed; only blob centroids retained |
| `pipeline` materialised every **sampled** frame | ≈ **31 GB** at 10 fps | Bounded by `MAX_ANALYSIS_FRAME_BYTES` (1200 MB) with adaptive sample rate and a hard frame-count guard |

Memory is now bounded at ~1.3 GB regardless of video length. Frames are never
rescaled, so court-homography and overlay pixel coordinates stay valid.

**This is the clearest argument for testing on real, long footage:** an 8-minute
1080p match is an entirely ordinary upload, and the app would have crashed on
every single one.

---

## Revised scores

Updated from the earlier synthetic-only assessment. Rubric: 0 fails … 5 excellent.

| Dimension | Synthetic-only | **Real footage** | Why it changed |
|---|---|---|---|
| Upload handling | 5 | **5** | Unchanged |
| Video processing | 4 | **3** | Two OOM crashes on ordinary long footage; fixed, but latency now varies 0.13×–6.38× realtime |
| Pose / keypoint detection | not scored | **4** | 76–88% coverage, 0.72–0.85 confidence — genuinely good |
| Player tracking | 2 | **1** | 5–20× identity fragmentation on real bodies, worse than synthetic suggested |
| Stroke recognition | not scored | **1** | Physically impossible rates; counts unusable as statistics |
| Coaching feedback | 4 | **3** | Structure and evidence-linking are good, but inputs derived from shot counts are unreliable |
| Safety of coaching advice | 5 | **5** | Unchanged — refuses diagnosis, refers to a professional |
| UI / UX | 4 | **4** | Unchanged |
| Performance | 5 | **3** | Up to 6.38× realtime; memory bugs (now fixed) |
| Uncertainty communication | — | **5** | Every degradation flagged; nothing silently invented |
| **Overall confidence** | 3 | **2.5** | Infrastructure, safety and honesty are strong; the analysis layer is not trustworthy yet |

**The honest summary:** the platform around the model is solid — auth,
isolation, upload safety, quality gating, and above all its refusal to
overclaim. The vision pipeline's *plumbing* works on real footage and pose
estimation is genuinely usable. But **tracking and stroke recognition are not
fit for the coaching claims built on them**, and no amount of UI polish fixes
that. Those two need the model work in `NEXT_STEPS.md` H2 and H3.
