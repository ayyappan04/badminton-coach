# System Architecture — AI Badminton Coach

## 1. Guiding principles

- **Honesty over flash.** Every derived measurement (court geometry, pose, shuttle position, shot label) carries a numeric confidence score and a plain-language caveat. Nothing is presented as ground truth.
- **Privacy by construction.** User-uploaded footage is stored separately from any footage used for model training. Nothing crosses that boundary without an explicit, revocable opt-in.
- **Modularity.** The computer-vision pipeline is a chain of independent stages with typed inputs/outputs, so any stage (e.g. shuttle detection) can be swapped for a better model later without touching the rest of the system.
- **MVP-first.** Reliable, simple analysis beats unreliable, impressive analysis. Advanced biomechanics/3D simulation are additive layers on top of a working core, not a prerequisite for shipping.

## 2. High-level component diagram

```
┌───────────────────────────────────────────────────────────────────────────┐
│                              Client (React)                               │
│  Welcome/Coach  │  Player Dashboard  │  Community & Training               │
└───────────────────────────────┬────────────────────────────────────────────┘
                                 │ REST/JSON (+ signed media URLs)
┌───────────────────────────────▼────────────────────────────────────────────┐
│                          API Gateway (FastAPI)                             │
│  auth · videos · analysis · profile · community · consent/privacy          │
└───────────────────────────────┬────────────────────────────────────────────┘
                                 │
        ┌────────────────────────┼─────────────────────────┐
        ▼                        ▼                          ▼
┌───────────────┐      ┌───────────────────┐      ┌──────────────────────┐
│  Relational DB │      │  Object storage    │      │  Background worker    │
│  (Postgres in  │      │  (video, clips,    │      │  queue (analysis      │
│  prod / SQLite │      │  overlays, heat-   │      │  jobs, profile        │
│  in dev)       │      │  maps)             │      │  recompute)           │
└───────────────┘      └───────────────────┘      └──────────┬───────────┘
                                                               │
                                              ┌────────────────▼───────────────┐
                                              │      CV & Coaching Pipeline     │
                                              │  (modular stages, see           │
                                              │  CV_PIPELINE.md)                │
                                              └─────────────────────────────────┘
```

## 3. Services / modules

Each of these is a separate Python package under `backend/app/services/` (or a separate microservice in a scaled deployment). They communicate through well-defined data contracts (Pydantic models), so a monolith-to-microservices split later is mechanical, not a rewrite.

| Module | Responsibility | MVP status |
|---|---|---|
| Video ingestion & transcoding | Accept upload, validate, normalize container/fps | Implemented (basic) |
| Frame extraction | Decode frames at analysis frame rate | Implemented |
| Court detection & calibration | Find court lines, estimate homography to real-world coordinates | Implemented (semi-automatic) |
| Player detection & tracking | Detect people, track IDs across frames, let user tag "this is me" | Implemented (classical CV) |
| Pose estimation | Per-player body landmarks | Implemented (MediaPipe) |
| Racket detection & tracking | Racket head/grip position and orientation | Planned (Phase 2) |
| Shuttle detection & trajectory | Shuttle position, speed, landing zone | Implemented (experimental, low confidence) |
| Shot recognition | Classify shot type, side, offensive/defensive | Implemented (heuristic, Phase 2 = learned model) |
| Rally segmentation | Split match into rallies, detect start/end | Implemented (heuristic) |
| Court-coordinate transform | Pixel → court-meters mapping | Implemented (via homography) |
| Biomechanical feature estimation | Joint angles, balance, stance | Implemented (estimate-labeled) |
| Tactical pattern analysis | Positioning tendencies, formations, shot patterns | Implemented (rule-based, Phase 2 = learned) |
| Longitudinal player profiling | Cross-match trends, play-style classification | Implemented |
| Recommendation generation | Drills, training plan, priorities | Implemented (rule-based library, Phase 3 = adaptive) |
| Video rendering / overlays | Draw skeletons, trails, court lines, heatmaps | Implemented |
| Auth | User accounts, sessions | Implemented (JWT, minimal) |
| Consent & privacy management | Recording retention, training opt-in, sharing scopes | Implemented |
| Community & social | Friends, sharing, planning | Implemented (MVP CRUD) |

## 4. Technology stack

**Backend**
- Python 3.9+, FastAPI, Pydantic, SQLAlchemy
- SQLite for local/dev, Postgres for production (same SQLAlchemy models — swap the connection string)
- OpenCV for frame extraction, classical court-line detection (Hough transform), overlay rendering, and video I/O
- MediaPipe Pose for per-player body-landmark estimation (runs fully offline, no external model download at runtime)
- Background jobs run via a lightweight in-process thread pool queue for the MVP (`backend/app/worker.py`); swappable for Celery + Redis/SQS at scale without changing pipeline code
- Object storage: local filesystem in dev (`backend/storage/`), S3-compatible bucket in production

**Frontend**
- React + TypeScript + Vite
- Tailwind CSS for styling
- Recharts for radar/spider charts and trend graphs
- HTML5 `<video>` + `<canvas>` overlay layer for synchronized skeleton/court/shuttle overlays

**Why not deep-learning detectors (YOLO, etc.) for the MVP?** They give better accuracy but add heavy dependencies (PyTorch, GPU expectations, licensed weight downloads) that hurt the "runs anywhere, ships fast" goal of an MVP. The player-tracking and shuttle-detection modules are built as swappable interfaces (`Detector` protocol) so a YOLOv8/RT-DETR-based detector can be dropped in during Phase 2 without touching downstream code.

## 5. Data flow for one uploaded match

1. Client uploads video → stored in object storage, `Video` row created with status `uploaded`.
2. API enqueues an analysis job → worker picks it up, status → `processing`.
3. Pipeline runs stage by stage (see CV_PIPELINE.md), each stage writing structured results + confidence to the DB and any derived media (overlay clips, heatmaps) to object storage.
4. If the pipeline can't confidently identify which tracked person is the user, status → `needs_player_selection`; client shows tracked candidates, user clicks theirs, processing resumes.
5. On completion, status → `analyzed`; coaching-insight generation runs, producing timestamped insights linked to video moments.
6. Longitudinal profile job re-aggregates the player's profile across all their analyzed matches.
7. Client polls/subscribes to status and renders the dashboard once `analyzed`.

## 6. Deployment shape (future, beyond MVP)

- API + worker containers behind a load balancer; worker pool scales independently since CV processing is the bottleneck.
- Object storage behind signed URLs (never expose raw storage paths to the client).
- Postgres with read replica for dashboard queries once community/social features add read load.
- Separate, access-controlled "training data lake" (see PRIVACY_AND_CONSENT.md) that only ingests footage with verified licensing/consent — physically and permission-wise isolated from user-upload storage.
