# Version 2 Design — AI Badminton Coach

This document covers the full V2 design: product requirements, user stories,
architecture, CV pipeline, database, API, UI, models, training data, privacy,
failure handling, testing, rollout, metrics, journeys, and example outputs.
It also classifies every feature by buildability (see §18) — the single most
important section for keeping V2 honest.

---

## 1. Product requirements

**Goal:** move from "video analysis tool" to "personalized coaching system."
A player should be able to upload matches over weeks and feel that the app
knows their game: their habits, their weaknesses, their progress, and what to
train next — all grounded in visible video evidence, never in invented
precision.

Functional requirements (V2 scope):

| # | Requirement | Priority |
|---|---|---|
| R1 | Pre-analysis video-quality assessment with score + recording advice | P0 |
| R2 | Improved court detection (perspective-aware corner fit, quality estimate) | P0 |
| R3 | Improved rally segmentation (smoothed, hysteresis-based) | P0 |
| R4 | Tracking persistence through short occlusions; camera-cut detection | P0 |
| R5 | Rally phase timeline (serve/return/attack/neutral/defense/ending) with click-to-seek | P0 |
| R6 | Match analytics: rally stats, serve/return patterns, shot combinations, front/rear dominance, fatigue trend, momentum proxy, pressure zones | P0 |
| R7 | Technique scorecards v2: 10 dimensions with confidence + data-quality flags | P0 |
| R8 | Strategy recommendations tied to observed patterns | P0 |
| R9 | Adaptive training plan (weekly focus, daily drills, milestones) that changes per upload | P1 |
| R10 | Comparison Studio: side-by-side user clip vs. animated reference, frame stepping, checkpoints, configurable by level/handedness/context | P1 |
| R11 | Conversational coach that answers questions from the player's own data | P1 |
| R12 | Match-to-match comparison | P1 |
| R13 | Manual corrections (court corners, player identity) stored as feedback | P1 |
| R14 | Clubs, training streaks, practice scheduling | P2 |
| R15 | Per-dimension progress trends | P1 |

Non-functional: every derived number carries confidence ∈ [0,1] and
limitation tags; degraded video still yields partial results with explicit
"what we could not measure" notes; user video never trains models without
per-user opt-in.

## 2. User stories

- *As a club player*, I upload Sunday's match and within minutes see the three moments that cost me the most points, each linked to the video.
- *As an improver*, I ask the coach "why am I losing points at the net?" and get an answer built from my own net-shot stats and lunge-stability estimates, not a generic article.
- *As a doubles player*, I see how often my team was side-by-side while attacking, with clips of the rotations we missed.
- *As a competitive player*, I compare this month's match to one from six weeks ago and see recovery speed and shot variety moving in the right direction.
- *As a beginner*, I open the Comparison Studio for the smash, set it to "beginner, right-handed," and step through the phases next to my own attempt.
- *As a privacy-conscious user*, I confirm my footage is private by default, delete a match and its analytics, and export everything the app derived about me.
- *As a club organizer*, I create a club space, schedule practices, and see who is on a training streak — without seeing anyone's private analysis.

## 3. Technical architecture (delta from V1)

V1's monolith-with-modules shape is retained; V2 adds stages and services
inside the same contracts:

```
Upload → [NEW] Video Quality Gate → Court Detection v2 → Tracking v2
      → Pose → Shuttle (experimental) → Rally Segmentation v2
      → [NEW] Rally Phase Analyzer → Shot Recognition
      → Biomechanics → [NEW] Match Analytics & Tactics → Insights
      → [NEW] Adaptive Plan Update → Profile Update
```

New/changed services:
- `cv_pipeline/video_quality.py` — pre-analysis gate; emits QualityReport (stored on Video), feeds limitation tags to every downstream stage.
- `cv_pipeline/court_detection.py` — upgraded: clusters Hough lines into horizontal/vertical families, intersects extremes for a perspective-aware quadrilateral; falls back to V1 bbox method, then to user-assisted calibration.
- `cv_pipeline/player_tracking.py` — upgraded: constant-velocity gap bridging re-links tracks through ≤N-frame occlusions; camera-cut boundaries (from quality gate) hard-reset the tracker.
- `cv_pipeline/rally_segmentation.py` — upgraded: moving-average smoothing + dual-threshold hysteresis.
- `cv_pipeline/rally_phases.py` — NEW: labels each rally's internal phases from shot order/intent.
- `tactics/match_analytics.py` — NEW: whole-match statistics, pattern mining, strategy recommendations.
- `coaching/coach_chat.py` — NEW: intent-routed conversational coach grounded in the player's stored data.
- `profiling` — upgraded: adaptive plan generation, per-dimension trends.
- `corrections` — NEW: UserCorrection records for court/identity fixes; audit trail; future training signal (only with consent).

Event-driven processing: jobs flow through the worker queue with per-stage
progress checkpoints; a failed stage marks partial results delivered rather
than discarding the whole job (each stage's output is persisted as it
completes). Model/feature versioning: `Video.pipeline_version` records the
exact pipeline release that produced results; re-analysis after upgrades is
explicit, never silent.

## 4. CV pipeline details (V2)

Stage-by-stage, with the honest mechanism:

1. **Quality gate** — resolution/fps from container; lighting = mean luma + histogram spread; motion blur = Laplacian variance (low = blurry); camera shake = mean absolute frame-to-frame difference of downsampled grayscale in static regions; camera cuts = histogram-correlation drops; court visibility = downstream calibration confidence backfilled into the report. Produces 0–100 score + targeted recording tips.
2. **Court detection v2** — line mask (bright/low-sat pixels) → probabilistic Hough → split segments by angle into near-horizontal / near-vertical families → take extreme lines per family → intersect for 4 corners → homography vs. official court meters. Confidence from line-family support and quad plausibility (area ratio, convexity). Fallback chain: V1 bbox extents → full-frame margin + `needs_user_calibration`.
3. **Tracking v2** — HOG detection (as V1; classifier upgrade is a Phase-3 model item) + IOU tracker with: (a) constant-velocity coasting for ≤8 missed frames, (b) post-pass track merging when a dead track's predicted position matches a new track's start within a radius and time window, (c) hard resets at camera cuts. Track quality = fraction of non-coasted frames.
4. **Rally segmentation v2** — motion energy per frame → moving-average smoothing (window ~0.7 s) → hysteresis: rally starts above T_high, ends below T_low for ≥ gap frames → min-duration filter → short-gap merge.
5. **Rally phases** — first self/opponent shot = serve; second = return; sliding window over remaining shots labels attack (offensive-intent majority for the analyzed player), defense (defensive majority), else neutral; final shot = rally-ending event. Phase confidence = min(shot confidences in window). **Rally outcomes (winner/forced/unforced/net/out) are NOT claimed in V2** — that requires shuttle-landing detection and/or score OCR (see §18); the ending event records who hit last and the shot type only.
6. **Match analytics** — computed from persisted shots/rallies/tracks: durations, shots-per-rally, serve/return type mixes, top 2- and 3-shot combinations (n-gram counts), front-vs-rear-court occupancy (court-Y split at net line), per-rally movement speed regression for a fatigue *indicator* (slope, flagged low-confidence), momentum proxy (rolling rally-duration/intensity trend — explicitly labeled a proxy because scores are unknown), opponent pressure zones (opponent heatmap peaks). Every block carries its own confidence and a `basis` string saying what it was computed from.
7. **Technique scores v2** — footwork, balance, stability, racket preparation (wrist-height-before-swing proxy), contact height, shot timing (swing-to-shot-interval consistency), recovery speed, movement efficiency (distance per rally vs. court coverage), body alignment (shoulder-hip line tilt at contact), execution consistency (variance of per-shot confidence-weighted features). All labeled "video-based estimate."

## 5. Database design (V2 additions)

```
videos                      + quality_score float, quality_report JSON,
                            + pipeline_version str
rallies                     + phases JSON [{phase,start_s,end_s,confidence}],
                            + ending_shot_type str, ending_track_role str
match_analytics   NEW       video_id FK unique, analytics JSON (blocks with
                            per-block confidence + basis), created_at
user_corrections  NEW       user_id, video_id, correction_type
                            (court_corners | player_identity), payload JSON,
                            applied bool  — feedback loop + audit trail
clubs             NEW       name, description, owner_user_id
club_memberships  NEW       club_id, user_id, role (member|coach|admin)
technique_references        + variants JSON {level, handedness, context notes},
                            + checkpoints JSON per phase
processing_jobs   NEW       video_id, stage, status, attempts, last_error,
                            started_at, finished_at  — retry + audit
```

Pose frames, shots, rallies stay row-per-event (replay visualization needs
frame-addressable data); match_analytics and profile snapshots are
pre-aggregated JSON (longitudinal queries need cheap reads). This dual
storage is deliberate: replay reads rows by frame index; trends read
aggregates by date.

## 6. API additions

```
GET  /videos/{id}/quality-report        quality score, sub-scores, recommendations
GET  /videos/{id}/phases                rally phase timeline (click-to-seek data)
GET  /videos/{id}/analytics             match analytics blocks
GET  /videos/compare?video_a&video_b    side-by-side stat deltas
PATCH /videos/{id}/calibration          {court_corners_px} → recompute homography,
                                        store UserCorrection, mark method=manual
POST /coach/ask                         {question} → {answer, evidence[], suggestions[]}
GET  /technique-references/{name}?level=&handedness=&context=
GET  /community/clubs · POST /community/clubs · POST /community/clubs/{id}/join
GET  /community/streak                  current training streak (weeks)
```

## 7. UI layout & component hierarchy

```
App
├── NavBar (Coach | Dashboard | Profile | Community)
├── Welcome
│   ├── CoachAvatar
│   ├── CoachChat            NEW — question box + suggestion chips + evidence links
│   └── QuickActions
├── Dashboard
│   ├── OverviewStrip        NEW — dev score, focus, strength, trend, next drill,
│   │                              coach message, upcoming practice
│   ├── MatchLibrary         + format filter, text search, compare picker
│   ├── VideoOverlayPlayer   (skeleton/court/shuttle/boxes toggles)
│   ├── PhaseTimeline        NEW — phase-colored rally bar, click-to-seek, legend
│   ├── QualityReportCard    NEW — score + recording tips + limitation tags
│   ├── MatchAnalyticsPanel  NEW — rally stats, shot mix, combos, front/rear,
│   │                              fatigue note, strategy recommendations
│   ├── InsightsPanel        (unchanged structure, links to studio)
│   ├── ScorecardsV2         10 dimensions, each with confidence
│   ├── HeatmapPanel · MovementTrails
│   ├── CompareDrawer        NEW — two-match stat deltas
│   └── ComparisonStudio     NEW modal — user clip | animated reference,
│                              phase scrubber, frame step, checkpoints,
│                              config (level/hand/context), errors, drills
├── Profile
│   ├── RadarChartPanel (11 dims) · AttributeBars
│   ├── DimensionTrend       NEW — pick a dimension, see per-session line
│   ├── PlayStyleEvidence · StrengthsWeaknesses
│   └── TrainingPlanV2       weekly focus, daily drills, milestones, re-analysis nudge
└── Community
    ├── FriendsPanel · PracticePlanner · PrivacyControls
    ├── ClubsPanel           NEW — create/join, roles
    └── StreakChip           NEW — consecutive training weeks
```

## 8. Model recommendations & training-data requirements

| Capability | V2 approach | Production model target | Training data needed |
|---|---|---|---|
| Player detection | HOG + IOU/coast tracker | YOLOv8-m or RT-DETR + ByteTrack | ~20–50k boxed frames across venues/angles; licensed or consented only |
| Pose | MediaPipe Pose | Keep; consider RTMPose for crowded doubles | none (pretrained) / fine-tune needs 5–10k annotated badminton poses |
| Shuttle | Motion-blob heuristic (experimental) | Small-object detector (TrackNet-style heatmap regression) | 30–80k annotated shuttle frames incl. motion blur; the single highest-value dataset to build |
| Shot classification | Rule-based on pose+timing | Temporal model (TCN/transformer) over pose+shuttle windows | 10–30k labeled shots across levels; annotation UI already spec'd in V1 governance docs |
| Rally outcome (winner/error) | **not claimed** | Shuttle-landing + score OCR ensemble | landing-zone labels + scoreboard frames |
| Court detection | Line-family quad fit | Keypoint CNN for court corners | 2–5k annotated court images, many venues |

All training data must flow through the V1 governance pipeline
(training_assets + consent_records + human review). User uploads join only
via explicit opt-in.

## 9. Privacy requirements (V2 delta)

V1 guarantees hold. New surface areas:
- Coach chat runs entirely on the player's own stored data; questions/answers are not shared or used for training.
- User corrections are stored per-user; using them as training signal requires the same opt-in as footage.
- Clubs: membership visible to club members only; performance data never auto-shared to clubs — team dashboards (Phase 3) will be per-metric opt-in.
- No face recognition anywhere; identity assignment is bounding-box selection by the user.
- Minors: age gate at signup; under-16 accounts default all sharing to private and disable public clips (enforced server-side on visibility writes).

## 10. Failure handling

- Quality gate hard-fails only unreadable files; low quality → proceed with degraded-mode flags, UI shows what was skipped and why.
- Each pipeline stage try/excepts into `processing_jobs` with attempts count; a stage failure delivers partial results (everything persisted so far) and marks the stage failed rather than the video.
- Worker retries a failed stage once; second failure surfaces a user-readable message plus recording advice when relevant.
- Camera cuts reset tracking rather than corrupting identities; if cuts > threshold, positioning analytics are suppressed with an explanation.
- Overlay/analytics endpoints degrade to 404-with-reason when the in-process cache is cold (server restart) and offer re-processing.

## 11. Test strategy

- Unit: quality metrics on synthetic frames (dark/blurred/shaken variants), quad-fit geometry, hysteresis segmentation edge cases, n-gram pattern mining, phase labeling, streak computation.
- Integration: synthetic video through the full pipeline (existing harness), asserting phases/analytics/quality rows exist and carry confidences.
- API: auth’d happy paths + ownership checks for every new endpoint.
- Frontend: typecheck + preview-driven visual verification of each new panel; click-to-seek behavior of the phase timeline.
- Honesty tests: assert no endpoint emits a confidence > cap for heuristic stages; assert rally outcomes are never labeled winner/error in V2.

## 12. Rollout plan

1. Ship backend V2 pipeline behind `pipeline_version=2.0.0`; new uploads use it, old videos keep V1 results with a "re-analyze with V2" button.
2. Ship dashboard v2 + quality gate to all users (pure additive UI).
3. Ship studio + coach chat (Phase 2 features) once reference content is reviewed by a qualified coach.
4. Phase 3 (clubs at scale, shuttle model, racket tracking) gated on the annotated-data milestones in §8.
5. Each rollout step: monitor processing failure rate, insight-confidence distribution, and correction submissions as the feedback signal.

## 13. Success metrics

- ≥90% of uploads reach `analyzed` (incl. degraded mode) without manual intervention.
- Median processing time ≤ 2× video duration on baseline hardware.
- ≥60% of analyzed matches get at least one insight clicked-through to video.
- ≥40% of active users open the Comparison Studio within 2 weeks.
- Correction rate on court/identity < 15% of videos (proxy for detection quality).
- 4-week retention of uploaders; training-plan drill completion self-reports.
- Zero privacy escalations: no video shared beyond its visibility scope (audited).

## 14. Example user journeys

**Journey A — club player, singles.** Upload → quality gate says "82/100 — good; tip: raise camera ~1 m for better depth separation" → picks self from 2 tracks → dashboard shows phase timeline; clicks the red ending segment of rally 7 → video seeks to the lost point → insight: late split step (68%) → opens studio, compares split-step reference at intermediate level → adds the shadow-timing drill to this week's plan.

**Journey B — doubles pair.** Upload doubles match → 4 tracks, user tags self + partner → formation panel: side-by-side during 71% of attacking sequences (65%) → strategy card: "shift to front-back when your team initiates attack" → shares one rotation clip to the club group with friends-only visibility.

**Journey C — progress check.** After 6 uploads, Profile shows recovery-speed trend up 12 points; coach chat: "what should I train before my tournament?" → coach answers with the two lowest dimensions, this week's focus, and three drills, each linking to a video moment.

## 15. Example coaching outputs

See COACHING_EXAMPLES.md for V1 examples; V2 adds pattern-level outputs:

> **Pattern — predictable lift (confidence 63%)**
> Observed: after opponent drives to your backhand side, you lifted cross-court on 7 of 9 tracked occasions.
> Why it matters: repeated to this degree, a pattern becomes readable; opponents can pre-move to the rear corner.
> Try: mix in straight blocks or drives from that position.
> Evidence: rallies 4, 9, 12 (click to view). Limitations: shot direction inferred from your movement and contact side, not shuttle tracking — treat as directional.

> **Strategy — use your rear-court pressure (confidence 58%)**
> You averaged 3.1 more shots per rally when your first attack came after pushing the opponent behind the doubles service line. Consider building rallies toward deep clears before committing to the smash.
> Basis: rally length vs. opponent depth at first offensive shot, 18 rallies. This is a proxy — actual point outcomes are unknown without score tracking.

## 16. Component/feature versioning

`pipeline_version` on every video; `feature_version` inside each
match_analytics block (analytics can be recomputed from stored rows without
re-running CV). UI shows "Analyzed with pipeline 2.0.0" in the quality card.

## 17. Conversational coach design (honest scope)

V2's coach is **retrieval + templates over the player's own data**, not a
free-form LLM: a question is intent-matched (net play, footwork, smash,
doubles rotation, balance, training priorities, shot selection, progress);
each intent handler queries the DB (insights, shots, scores, trends) and
fills a coach-voiced template with real numbers, timestamps, and drill links,
plus an explicit confidence line. Unrecognized questions get a graceful
fallback listing what the coach *can* answer. This is deterministic,
auditable, and cannot hallucinate stats. A hosted LLM can later replace the
template layer (grounded on the same retrieval), which is a Phase-3 decision
with its own privacy review. The coach always includes the boundary line:
it complements, not replaces, in-person coaching or medical advice.

## 18. Buildability classification (the honesty table)

**Reliable now (shipped in this V2 code):** quality gate; court quad-fit with
fallbacks; tracking gap-bridging + cut resets; rally segmentation v2; rally
phases; match analytics + pattern mining + strategy recs (proxy-labeled);
technique scores v2; adaptive plans; comparison studio (animated reference,
not 3D); template-grounded coach chat; compare; corrections; clubs/streaks.

**Needs model training (not shipped as claims):** trained shot classifier;
shuttle trajectory/speed/landing; racket detection (position/angle/speed);
rally outcomes (winner/forced/unforced/net/out); serve-type detection beyond
first-shot heuristics; smash-vs-drop disguise analysis.

**Needs better calibration (multi-camera or user-assisted):** true contact
height in meters; net-clearance estimates; clear depth in meters; jump-height
estimates.

**Experimental until accuracy improves (present but capped-confidence and
labeled):** shuttle motion-blob tracking; fatigue slope; momentum proxy;
cross-court vs. straight classification (movement-inferred only); doubles
communication-pattern inference.
