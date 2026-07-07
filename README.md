# ShuttleSense — AI Badminton Coach (V2)

A badminton coaching application: upload a match recording, get court/player
detection, pose-based technique and footwork analysis, rally-phase and shot
recognition, match analytics with strategy recommendations, timestamped
coaching insights, a technique Comparison Studio, a conversational coach
grounded in your own match data, and a longitudinal player profile that
builds across matches.

See [docs/](docs/) for the full system design:

- [V2_DESIGN.md](docs/V2_DESIGN.md) — **Version 2 design**: requirements, user stories, CV pipeline v2, DB/API deltas, model & training-data plan, rollout, metrics, and the feature buildability classification
- [ARCHITECTURE.md](docs/ARCHITECTURE.md) — components, tech stack, data flow
- [DATABASE_SCHEMA.md](docs/DATABASE_SCHEMA.md)
- [API_DESIGN.md](docs/API_DESIGN.md)
- [CV_PIPELINE.md](docs/CV_PIPELINE.md) — stage-by-stage computer vision design
- [PRIVACY_AND_CONSENT.md](docs/PRIVACY_AND_CONSENT.md) — training-data rights, consent controls
- [WIREFRAMES.md](docs/WIREFRAMES.md) — page layouts
- [ROADMAP.md](docs/ROADMAP.md) — phased plan
- [COACHING_EXAMPLES.md](docs/COACHING_EXAMPLES.md) — example coaching output

## What's new in V2

- **Video-quality gate**: every upload is scored 0–100 (resolution, frame rate,
  lighting, sharpness, camera shake, scene cuts) with concrete recording tips;
  poor footage still gets partial analysis with explicit limitations.
- **CV accuracy upgrades**: perspective-aware court-corner fitting (line-family
  intersection instead of a bounding box), tracking that coasts through short
  occlusions and re-links broken tracks (with hard resets at camera cuts), and
  smoothed hysteresis-based rally segmentation.
- **Rally phase timeline**: each rally split into serve / return / attack /
  neutral / defense / ending segments, color-coded and click-to-seek. Rally
  *outcomes* (winner/error) are deliberately not claimed — that needs
  shuttle-landing detection (see V2_DESIGN §18).
- **Match analytics & tactics**: rally stats, serve/return patterns, shot-mix,
  repeated shot-combination mining (predictability), front/rear-court
  dominance, movement-speed fatigue indicator, momentum proxy, opponent
  pressure zones, and rule-based strategy recommendations — every block
  carries a confidence and a "computed from" basis.
- **Technique scorecards v2**: ten dimensions (footwork, balance, stability,
  racket preparation, contact height, shot timing, recovery speed, movement
  efficiency, body alignment, consistency), each showing the proxy it was
  measured by.
- **Comparison Studio**: your clip side-by-side with an animated reference,
  slow motion, frame stepping, per-phase checkpoints, configurable by level /
  handedness / tactical context; 24 shot & movement references seeded.
- **Conversational coach**: intent-routed retrieval over *your* stored data —
  deterministic, cannot hallucinate stats, links answers to video moments.
- **Dashboard v2**: overview strip (development score, focus, strength, trend,
  next drill, coach message), match comparison, library search/filters.
- **Profile v2**: per-dimension progress trends. **Community v2**: clubs with
  roles, training streaks.
- **Reliability**: dashboard endpoints rebuild from persisted rows (survive
  server restarts), `pipeline_version` recorded per video, user corrections
  (court corners) stored as an auditable feedback loop.

## What's implemented (Phase 0 / MVP)

- Real (not mocked) CV pipeline: OpenCV court-line detection, HOG-based player
  tracking, MediaPipe pose estimation, motion-heuristic shuttle detection,
  rule-based rally/shot segmentation, 2D biomechanics estimates (joint angles,
  stance, stability, center of mass), tactical analysis (heatmaps, recovery
  timing, doubles formation).
- Every estimate carries a confidence score and limitation tags — nothing is
  presented as certain.
- Coaching-insight generation, a technique-reference "Correct Form" library,
  drill library, and a longitudinal player profile (radar scores, play-style
  classification with evidence, training plan) that updates as more matches
  are analyzed.
- FastAPI backend with SQLite (dev) persistence; React + TypeScript + Tailwind
  frontend (dark-navy professional theme) with four pages: Welcome/Coach,
  Player Dashboard, Player Profile (attribute spider chart, stat breakdown,
  play-style evidence, progress-over-time trend, training plan), and
  Community & Training.
- Consent/privacy controls (training-data opt-in, sharing scopes, retention,
  account deletion) and a structurally separate training-data-governance
  schema (licensing, consent records, human-in-the-loop annotation status).

Known MVP limitations (see docs/ROADMAP.md for the plan to address each):
classical CV detectors (not deep-learning) for player tracking, shuttle
detection is experimental, shot recognition is rule-based rather than a
trained classifier, and the technique simulator uses an animated stick figure
rather than full 3D skeletal animation.

## Running it locally

### Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8123
```

This creates `backend/app.db` (SQLite), seeds the drill/technique-reference
library automatically, and serves the API at `http://127.0.0.1:8123/api/v1`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Visit `http://localhost:5173`. The Vite dev server proxies `/api` to the
backend on port 8123 (see `frontend/vite.config.ts`).

### Generating a test video

`backend/tests/make_synthetic_video.py` generates a synthetic court video for
pipeline smoke-testing (it won't trigger real player detection since it has no
real human silhouettes — use real match footage to exercise full detection).

```bash
python backend/tests/make_synthetic_video.py /tmp/synthetic_match.mp4
```
