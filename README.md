<div align="center">

# 🏸 ShuttleSense

**An AI badminton coach that analyses your match video — and tells you how confident it actually is.**

[Quick start](#quick-start) · [What it does](#what-it-does) · [How well it works](#how-well-it-works-measured) · [Architecture](#architecture) · [Security](#security) · [Testing](#testing) · [Roadmap](#roadmap)

</div>

---

Upload a match recording and get court detection, player tracking, pose-based
technique and footwork analysis, rally-phase segmentation, tactical patterns,
timestamped coaching insights, a technique comparison studio, and a player
profile that develops across matches.

**The design principle is honesty about uncertainty.** Every derived number
carries a confidence score and a "computed from" basis. When the pipeline
can't see something reliably it says so and degrades — it does not invent a
court, a stroke, or a verdict. Rally outcomes (winner / forced error /
unforced error) are deliberately **not** claimed, because the system cannot
determine them without shuttle-landing detection.

---

## Quick start

**Requirements:** Python 3.9+ (3.11+ recommended — see [note](#a-note-on-the-python-version)), Node 20+, ~2 GB disk.

```bash
git clone https://github.com/ayyappan04/badminton-coach.git
cd badminton-coach
cp .env.example backend/.env          # defaults are safe for local dev
```

**Backend** (terminal 1):

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8123
```

**Frontend** (terminal 2):

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**, create an account, and upload a match.

The database (SQLite) and the drill/technique library are created automatically
on first start. No migration step is needed for a fresh install.

> **Emails never leave your machine in development.** The default mail backend
> is `console`: verification and reset messages are captured in an in-process
> outbox and logged to the terminal. See [Email setup](#email-setup).

### Optional: demo data

```bash
python -m app.seed_content            # drills + 24 technique references
```

---

## What it does

### 1 · Coach (landing)

Opens on a greeting, your current improvement focus with the numbers behind
it, and one obvious next action. Below that, the coach answers questions about
**your** matches — "why am I losing points at the net?", "what should I train
this week?" — as retrieval over your own stored analysis, with deep links to
the exact video moment.

There is **no LLM** in this path. It is intent-routed retrieval over your
database rows with fixed templates, which means it cannot hallucinate a
statistic. Injury and pain questions are gated *before* routing: the coach
declines to diagnose and refers you to a physiotherapist.

### 2 · Matches

The analysis workspace. A match library on the left, and the selected match on
the right: video with toggleable overlays, an analytical hero, then five tabs
so you aren't scrolling through ten sections to understand a session.

**Match performance hero** — overall score (the mean of the dimensions actually
measured, labelled as such), the three coaching areas, analysis confidence,
tracked shots, rallies and recording quality. Below 50% confidence the panel
says so rather than presenting estimates as measurements.

| Tab | What you get |
|---|---|
| **Overview** | Recording quality, rally & phase timeline (click any segment to seek), coaching insights with evidence links, strategy recommendations, coach review |
| **Movement** | Footwork, recovery speed and movement efficiency with the proxy each was measured by · court dominance · movement-speed trend · court coverage heatmap |
| **Technique** | Racket preparation, contact height, shot timing, body alignment, consistency · balance & stability · Comparison Studio launcher |
| **Tactics** | Repeated shot patterns and predictability · serve & return · opponent pressure zones · doubles rotation |
| **Shots** | Rally shape · shot mix table · every tracked shot with timestamp, contact, intent and confidence — select a row to jump the video there |

Plus **Compare matches** for side-by-side deltas, and the **Comparison Studio**:
your clip beside an animated reference with slow motion, frame stepping and
per-phase checkpoints, configurable by level, handedness and tactical context.

### 3 · Progress

Development score with a sparkline across sessions, current focus and analysis
confidence. Play-style classification **with the evidence behind it**. The
attribute radar sits beside a numeric breakdown — every dimension with its
value and its change since the previous session, so nobody has to estimate a
number from a polygon. Then strengths, focus areas, a per-dimension trend
chart, and the training plan.

### 4 · Community

Friends, clubs with team dashboards (opt-in per metric), shared clips,
practice planning, friendly challenges, training streaks, progress milestones,
and granular privacy controls.

---

## How well it works (measured)

Honest numbers from the harnesses in this repo, not aspirations.

### Synthetic condition matrix — `docs/evidence/video-matrix.json`

14 locally generated clips covering lighting, blur, shake, cuts, resolution,
frame rate, orientation, occlusion, and non-badminton footage.

| Signal | Result |
|---|---|
| Quality gate discriminates | low-light **52**, motion blur **60**, non-badminton **53**, good footage **84** |
| Court detection fails safe | 0.15 confidence + `needs_user_calibration` — never invents geometry |
| Camera cuts | Detected; tracking resets; user advised |
| Player tracking | **0 tracks** under occlusion, partial court, and low resolution |
| Latency | 0.1×–0.7× realtime on CPU |

### Real footage matrix — [full results](docs/REAL_FOOTAGE_RESULTS.md)

13.6 minutes of openly-licensed real badminton (CC0 / public domain / CC BY /
CC BY-SA) from Wikimedia Commons — 320×240 school play up to 1920×1080 elite
tour broadcast.

| Signal | Result |
|---|---|
| **Pose estimation** | **76–88% coverage**, 0.72–0.85 confidence — *newly validated*, was unmeasurable on synthetic clips |
| **Court detection** | Best on broadcast (**0.89**); falls back honestly on unusable footage |
| **Player tracking** | **11–65 tracks for 2–4 players** — 5–20× identity fragmentation |
| **Stroke recognition** | **131 shots/min** on one clip — physically impossible; counts unusable |
| **Shuttle detection** | 13,205 "points" on an 8-minute clip — noise |
| **Limitation flags** | Correct on every clip — nothing silently invented |

**Testing on long real footage also found two crashes** that synthetic clips
(all ≤12 s) could never expose: the shuttle detector and the pipeline each
materialised every frame in memory — ~94 GB and ~31 GB respectively for an
8.4-minute 1080p match. Both fixed; memory is now bounded at ~1.3 GB.

```bash
cd backend
python -m tests.fetch_real_footage        # polite, cached, attribution auto-generated
python -m tests.run_real_footage_matrix
```

Attribution: `docs/evidence/real-footage-attribution.md`.

### BWF footage

**Not downloaded** — it is rights-reserved, and downloading it would breach
both the platform terms and the licence. It is covered *observationally*
instead, via a structured protocol:
**[docs/BWF_MANUAL_TEST_PROTOCOL.md](docs/BWF_MANUAL_TEST_PROTOCOL.md)**.

If you hold a licence covering analysis use, the automated harness is
source-agnostic — drop files in and add them to
`backend/tests/footage_manifest.py`.

### What is *not* validated

| Capability | Status |
|---|---|
| Stroke recognition | **Not fit for purpose** — measured at up to 131 shots/min, which is physically impossible. Counts and everything derived from them (shot mix, patterns) are unreliable |
| Player tracking | **Fails** — 5–20× identity fragmentation on real footage; 0 tracks under synthetic occlusion |
| Shuttle tracking | **Experimental** — 13,205 false points on an 8-minute clip; confidence capped at 0.5 |
| Cross-match comparison | **Invalid between different sample rates** — long videos are analysed at a lower fps, which changes shot counts |
| Racket detection | **Not implemented** — the "racket path" overlay is a wrist estimate |
| Rally outcomes | **Deliberately not claimed** |

**Overall confidence: 2.5/5.** The platform — auth, isolation, upload safety,
quality gating, and its refusal to overclaim — is solid, and pose estimation is
genuinely usable. The tracking and stroke layers are not yet trustworthy enough
for the coaching claims built on them. Full scoring:
[docs/REAL_FOOTAGE_RESULTS.md](docs/REAL_FOOTAGE_RESULTS.md).

`docs/V2_DESIGN.md §18` classifies every feature as reliable-now, needs-model-
training, needs-calibration, or experimental.

---

## Architecture

Three tiers, split along one line: **large bytes move directly through object
storage; Vercel serves the application, not the video pipeline.**

```
                         ┌─────────────────────────┐
                         │        Browser          │
                         │  React / Vite (Vercel)  │
                         └────────────┬────────────┘
          small JSON control calls    │    video bytes (TUS, resumable)
                     ┌────────────────┴────────┴────────────────┐
                     ▼                                          ▼
          ┌──────────────────────┐                   ┌──────────────────────┐
          │  Vercel (static SPA) │                   │  Supabase Storage    │
          └──────────┬───────────┘                   │  private buckets     │
                     │ /api/*                        └───────────┬──────────┘
                     ▼                                           │
          ┌──────────────────────┐                               │
          │  FastAPI  (container)│  control plane only           │
          │  72 endpoints        │  never a data pipe            │
          └──────────┬───────────┘                               │
              ┌──────▼───────────────────────────────────────────▼───────┐
              │  Supabase: Auth · Postgres 17 · RLS · pgmq · Realtime    │
              └────────────────────────┬────────────────────────────────┘
                                       │ durable queued jobs
                                       ▼
                        ┌──────────────────────────────┐
                        │  Python Worker (container)   │
                        │  FFmpeg · OpenCV · MediaPipe │
                        └──────────────┬───────────────┘
                                       ▼
   probe → validate → normalize → quality gate → court detection → tracking
   → pose → shuttle → rally → phases → shots → biomechanics → tactics
   → insights → profile
```

Video bytes take exactly two paths, and neither touches Vercel or the API:
`browser → storage` on upload, `storage → worker` on processing, and
`storage → browser` for playback via a short-lived signed URL.

**Full detail: [docs/PRODUCTION_ARCHITECTURE.md](docs/PRODUCTION_ARCHITECTURE.md).**
Getting it deployed: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).
Schema and provenance: [docs/DATA_MODEL.md](docs/DATA_MODEL.md).
Runbook: [docs/OPERATIONS.md](docs/OPERATIONS.md).

```
backend/app/
  api/         auth · uploads · videos · profile · technique · community
               consent · coach · coach_reviews · integration
  core/        config · security · deps · observability · mailer · tokens
               rate_limit · uploads · auth_supabase
  storage/     VideoStorage protocol · local · supabase · immutable paths
  jobs/        JobDispatcher protocol · local · pgmq · handlers · runner
  media/       ffmpeg wrapper · probe · normalize · error taxonomy
  models/      18 model modules
  services/
    cv_pipeline/   14 stages
    coaching/      insight_generator · technique_scores · coach_chat
    tactics/       match_analytics · doubles_rotation
    profiling/     player_profile_builder
    upload_service · ingest_service · deletion_service · reconcile_service
    usage_service · video_state · events · pipeline_artifacts
  main.py      manage.py (ops CLI)
backend/alembic/    domain schema migrations
backend/tests/      241 tests + live smoke + two video matrices
supabase/migrations/  RLS · storage buckets/policies · pgmq · Realtime
frontend/src/
  ui/            design tokens + primitives
  lib/           supabase client · resumable upload · preflight
  pages/         Welcome · Dashboard (Matches) · Profile (Progress) ·
                 Community · AccountFlows
  components/
    match/       MatchSummary · MatchTabs · matchData
    …            26 feature components
docs/            architecture, operations, data model, security, evidence
```

**Stack:** FastAPI · SQLAlchemy 2 · Alembic · Supabase (Postgres 17, Auth,
Storage, Queues, Realtime) · PyJWT · FFmpeg · OpenCV · MediaPipe · React 19 ·
Vite · Tailwind 4 · Recharts · tus-js-client · Docker · Vercel.

---

## Interface

Dense information, calm presentation. The design system lives in
`frontend/src/ui`: semantic CSS tokens (surfaces, text, separators, accent,
semantic colours, viz palette, radii, motion) and a small set of primitives
that every screen composes from. No component reaches for a raw hex value.

Three rules do most of the work:

- **One analytical concept = one surface.** Related metrics sit together in a
  grouped panel rather than each getting its own card.
- **Direction is not sentiment.** A falling recovery time is an improvement; a
  rising error count is not. `Delta` takes both separately, and screen readers
  get words rather than a bare arrow.
- **Confidence is a metric, not a disclaimer.** Below 45% the value it
  accompanies is visually de-emphasised, and unmeasurable data renders as `—`
  with the reason attached — never a fabricated zero.

Numbers use tabular figures so columns align. Mobile gets bottom navigation
and stacked tables rather than a squeezed desktop layout, with no analytical
detail removed.

---

## Deployment

Three tiers, three secret scopes. Getting the last column wrong is a real
vulnerability, not a style issue.

| Tier | Runs | Holds |
|---|---|---|
| Vercel | the static SPA | `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` — public by definition |
| API + worker containers | FastAPI, the CV pipeline | `SUPABASE_SERVICE_ROLE_KEY`, `DATABASE_URL` — never in a browser |
| Supabase | identity, Postgres, private buckets, queues | the data |

```bash
# 1. domain schema (Alembic is the authority)
cd backend
export DATABASE_URL='postgresql+psycopg://postgres:PASSWORD@db.<ref>.supabase.co:5432/postgres'
python -m alembic upgrade head
```

```bash
# 2. platform configuration: RLS, storage buckets, queues, Realtime
supabase link --project-ref <ref> && supabase db push
```

```bash
# 3. API and worker containers
docker compose up --build
```

Or run the whole stack locally with no cloud credentials at all:

```bash
docker compose --env-file deploy/local.env -f docker-compose.yml -f docker-compose.local.yml up --build
```

```bash
# 4. check every dependency before sending traffic
cd backend && python manage.py doctor
```

Three switches decide whether a process behaves as the local MVP or as a
production tier. All default to local, so `pytest` and `uvicorn` work with no
environment set:

| Variable | Values |
|---|---|
| `STORAGE_BACKEND` | `local` · `supabase` |
| `JOB_BACKEND` | `local` · `pgmq` |
| `AUTH_MODE` | `legacy` · `supabase` · `dual` |

---

## Security

Full model and verification steps: **[docs/SECURITY.md](docs/SECURITY.md)**.
Review findings: **[docs/VALIDATION_AND_SECURITY_REPORT.md](docs/VALIDATION_AND_SECURITY_REPORT.md)**.

- **Auth:** email + password, bcrypt, JWT (HS256, 12 h). Signup, login,
  server-side logout, email verification, password reset — all with
  single-use expiring tokens hashed at rest.
- **Session revocation:** logout and password reset invalidate every
  outstanding token (`iat_ms` vs `tokens_valid_from`).
- **Isolation:** every video and derived result is owned by a user and checked
  server-side. Cross-user requests get **404**, not 403. 26 tests enforce it.
- **Uploads:** streaming size cap, container magic-byte validation, generated
  filenames, traversal-proof paths, per-user quotas.
- **Transport:** nosniff, DENY, strict CSP, Referrer-Policy, HSTS in
  production; docs disabled in production; CORS allowlist.
- **Rate limits** on login, signup, reset, lookup, and upload.
- **No secrets in the repo.** Production refuses to start without a real
  `JWT_SECRET`.

### Email setup

| Mode | Config | Behaviour |
|---|---|---|
| **Development (default)** | `MAIL_BACKEND=console` | Captured in-process and logged. **Never sent.** |
| **Local capture** | `MAIL_BACKEND=smtp`, `SMTP_HOST=localhost`, `SMTP_PORT=1025` | MailHog / Mailpit — browse at `localhost:8025` |
| **Hosted test inbox** | Mailtrap / Ethereal credentials | Safe sandbox |
| **Production** | Provider credentials from a secret manager | Real delivery |

```bash
docker run -p 1025:1025 -p 8025:8025 axllent/mailpit   # local capture
```

### A note on the Python version

The **container runtime is Python 3.12** (`backend/Dockerfile`), which is what
unblocked the patched releases of FastAPI, Starlette and `python-multipart`
that all require 3.10+. `requirements.txt` targets that runtime, and the image
has been built and the suite run inside it: **236 passed, 5 skipped**. The
skips are files `.dockerignore` deliberately excludes (`.git`, the frontend,
`.env.example`); those same tests run and pass outside the container.

The development machine has only Python 3.9, so the *local* results come from
`requirements-py39.txt` — the older, 3.9-capped pin set. Both are exercised:
241 locally (including the repo-level checks), 236 in the image.

The image ships Debian bookworm's **ffmpeg 5.1.9**. Every operation the media
pipeline performs is verified working on it, including rotation baking.

---

## Testing

```bash
cd backend && source .venv/bin/activate

python -m pytest tests/ -q                 # 241 tests
python -m pytest -m "not integration" -q   # fast subset (skips the CV end-to-end)
uvicorn app.main:app --port 8131 &         # then, in another shell:
python -m tests.smoke_live                 # 35 live end-to-end checks

python -m tests.run_video_matrix           # 14 synthetic scenarios
python -m tests.fetch_real_footage         # openly-licensed real clips
python -m tests.run_real_footage_matrix    # real footage through the pipeline

pip install pip-audit bandit && pip-audit && bandit -r app/ -ll
```

```bash
cd frontend
npx tsc -b --noEmit && npm run lint && npm audit && npm run build
```

| Suite | Covers |
|---|---|
| `test_auth.py` | Signup, login, logout, verification, reset, token forgery/expiry, rate limits |
| `test_authorization.py` | Cross-user isolation across 14 endpoints, stream ACL, coach-review scoping, API keys |
| `test_upload_security.py` | Type/size/signature validation, traversal, CRLF, unicode, quotas |
| `test_injection_and_hardening.py` | 10 injection strings, SQLi, error hygiene, security headers, medical safety |
| `test_production_config.py` | Production secret enforcement, verification gating, secret scan |
| `test_upload_lifecycle.py` | 12-state transition model, direct-to-storage authorization, idempotent completion, truncated-upload detection, quotas, refresh recovery |
| `test_storage_layer.py` | Immutable path construction, traversal rejection, bucket containment, streamed checksums, signed-read authorization |
| `test_job_system.py` | Atomic claim, lease expiry, heartbeat, stale-worker recovery, duplicate-delivery idempotency, reprocessing history |
| `test_media_pipeline.py` | ffprobe authority over declared type, permanent-vs-retryable classification, normalization planning, rotation baking, subprocess safety |
| `test_migrations.py` | Chain linearity, upgrade/downgrade round trip, model-vs-migration drift, offline SQL generation |
| `test_production_isolation.py` | Cross-user denial across 16 endpoints, coach grant/revoke, two-phase deletion, service-key containment in the client bundle |
| `test_e2e_pipeline.py` | Account → upload → queue → worker → results → signed playback → delete, driving the real worker loop |
| `test_storage_efficiency.py` | Pose landmarks resolve from artifact or rows transparently, fall back to Postgres when the artifact fails, and the result cache stays bounded |

**CI:** `docs/ci/ci.yml` runs tests, pip-audit, bandit, typecheck, lint, npm
audit, build, and a gitleaks scan. It lives under `docs/` because the push
credential lacks GitHub's `workflow` scope — see `docs/ci/README.md` to enable.

---

## Configuration

Everything is environment-driven; see **[.env.example](.env.example)**.

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `production` enables HSTS, disables docs, requires a real secret |
| `JWT_SECRET` | ephemeral in dev | **Required in production.** `openssl rand -hex 32` |
| `DATABASE_URL` | SQLite | Postgres in production |
| `STORAGE_DIR` | `./storage` | Private video storage — never web-served |
| `MAX_UPLOAD_MB` | 200 | Per-file cap, enforced while streaming |
| `MAX_UPLOADS_PER_HOUR` | 20 | Per-user rate limit |
| `MAX_STORAGE_MB_PER_USER` | 2048 | Per-user quota |
| `MAIL_BACKEND` | `console` | `smtp` to actually send |
| `REQUIRE_EMAIL_VERIFICATION` | true in prod | Block login until verified |
| `CORS_ORIGINS` | localhost:5173 | Explicit allowlist |

---

## Documentation

| Document | Contents |
|---|---|
| [SECURITY.md](docs/SECURITY.md) | Security model, verification, limitations |
| [VALIDATION_AND_SECURITY_REPORT.md](docs/VALIDATION_AND_SECURITY_REPORT.md) | Full review: findings, evidence, next steps |
| [REAL_FOOTAGE_RESULTS.md](docs/REAL_FOOTAGE_RESULTS.md) | Measured results on real badminton footage, with revised scores |
| [BWF_MANUAL_TEST_PROTOCOL.md](docs/BWF_MANUAL_TEST_PROTOCOL.md) | Lawful observational testing of broadcast footage |
| [V2_DESIGN.md](docs/V2_DESIGN.md) | Requirements, CV pipeline, buildability classification |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Components, stack, data flow |
| [CV_PIPELINE.md](docs/CV_PIPELINE.md) | Stage-by-stage vision design |
| [PRIVACY_AND_CONSENT.md](docs/PRIVACY_AND_CONSENT.md) | Training-data rights, consent |
| [DATABASE_SCHEMA.md](docs/DATABASE_SCHEMA.md) · [API_DESIGN.md](docs/API_DESIGN.md) · [WIREFRAMES.md](docs/WIREFRAMES.md) · [ROADMAP.md](docs/ROADMAP.md) | Reference |

---

## Roadmap

See **[NEXT_STEPS.md](docs/NEXT_STEPS.md)** for the prioritised plan with
effort estimates, and [ROADMAP.md](docs/ROADMAP.md) for phase history.

**Now:** upgrade to Python 3.11+ · replace the player detector to fix
occlusion tracking · train a shot classifier · reduce shuttle false positives.

**Next:** cookie-based sessions · killable processing subprocess · Alembic
migrations · object storage.

**Later:** trained shuttle detector · racket tracking · 3D pose lifting ·
multi-instance rate limiting · MFA/SSO.

---

## Contributing & licence

This is a portfolio/research project. The coaching content reflects widely
taught badminton fundamentals and **should be reviewed by a qualified coach
before any commercial use**. The app is not a substitute for in-person
coaching, physiotherapy, or medical advice, and it will tell users so.

No licence file is present yet — add one before publishing or accepting
contributions.
