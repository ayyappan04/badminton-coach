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

An animated coach that greets you, names your current improvement focus, and
answers questions about **your** matches — "why am I losing points at the
net?", "what should I train this week?". Answers are retrieval over your own
stored analysis with deep links to the exact video moment.

There is **no LLM** in this path. It is intent-routed retrieval over your
database rows with fixed templates, which means it cannot hallucinate a
statistic. Injury and pain questions are gated *before* routing: the coach
declines to diagnose and refers you to a physiotherapist.

### 2 · Dashboard

| Area | What you get |
|---|---|
| **Overview strip** | Development score, improvement focus, main strength, trend, next drill, coach message |
| **Recording quality** | 0–100 score with specific fixes ("record at 60 fps", "raise the camera") |
| **Video + overlays** | Skeleton, court, shuttle trail, tracked boxes — each toggleable |
| **Rally & phase timeline** | Serve / return / attack / neutral / defence / ending, colour-coded, click to seek |
| **Coaching insights** | Observation → impact → correction → drill, each with confidence and limitations |
| **Match analytics** | Rally stats, serve patterns, shot mix, repeated-pattern mining, court dominance, fatigue indicator, pressure zones |
| **Doubles rotation** | Formation split, rotation timing, missed rotations, partner spacing, open-middle detection |
| **Technique scorecards** | 10 dimensions, each showing the proxy it was measured by |
| **Comparison Studio** | Your clip beside an animated reference — slow motion, frame stepping, phase checkpoints, configurable by level / handedness / context |
| **Coach review** | Invite a real coach to one match; their notes appear beside the AI's |
| **Compare matches** | Side-by-side deltas between any two of your matches |

### 3 · Profile

Attribute radar across 9 dimensions, per-attribute breakdown, play-style
classification **with the evidence behind it**, strengths and weaknesses,
progress trend per dimension, and an adaptive training plan.

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

### Real footage matrix — `docs/evidence/real-footage-matrix.json`

Openly-licensed real badminton (CC0 / public domain / CC BY / CC BY-SA) from
Wikimedia Commons, including elite tour-level broadcast footage. Fetch and run:

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
| Stroke recognition accuracy | **Weak / unvalidated** — rule-based heuristic, not a trained classifier |
| Shuttle tracking | **Experimental** — emitted 170 false "shuttle points" on non-badminton footage; confidence capped at 0.5 |
| Tracking through occlusion | **Fails** — classical HOG detector, replacement planned |
| Racket detection | **Not implemented** — the "racket path" overlay is a wrist estimate |
| Rally outcomes | **Deliberately not claimed** |

`docs/V2_DESIGN.md §18` classifies every feature as reliable-now, needs-model-
training, needs-calibration, or experimental.

---

## Architecture

```
┌──────────────── Frontend (React 19 + TS + Vite + Tailwind 4) ─────────────────┐
│  Coach  ·  Dashboard  ·  Profile  ·  Community  ·  Account flows              │
└───────────────────────────────────┬───────────────────────────────────────────┘
                                    │ REST + Bearer JWT
┌───────────────────────────────────▼───────────────────────────────────────────┐
│  FastAPI  ·  9 routers  ·  63 endpoints (61 auth · 2 API-key · 8 public)      │
│  Security middleware · CORS allowlist · catch-all error handler               │
└───────────────────────────────────┬───────────────────────────────────────────┘
        ┌───────────────────────────┼────────────────────────────┐
        ▼                           ▼                            ▼
┌──────────────┐        ┌────────────────────┐       ┌──────────────────────┐
│ SQLAlchemy   │        │  Private storage   │       │  Worker (thread pool)│
│ SQLite / PG  │        │  (never web-served)│       │  analysis jobs       │
└──────────────┘        └────────────────────┘       └──────────┬───────────┘
                                                                 ▼
   quality gate → court detection → tracking → pose → shuttle → rally
   → phases → shots → biomechanics → tactics → insights → profile
```

```
backend/app/
  api/         auth · videos · profile · technique · community · consent
               coach · coach_reviews · integration
  core/        config · security · deps · mailer · tokens · rate_limit · uploads
  models/      15 model modules
  services/
    cv_pipeline/   14 stages
    coaching/      insight_generator · technique_scores · coach_chat
    tactics/       match_analytics · doubles_rotation
    profiling/     player_profile_builder
  worker.py
backend/tests/   98 tests + live smoke + two video matrices
frontend/src/    4 pages · 27 components
docs/            design, security, evidence
```

**Stack:** FastAPI · SQLAlchemy 2 · SQLite (dev) / Postgres (prod-ready) ·
PyJWT · passlib/bcrypt · OpenCV 4.10 · MediaPipe 0.10 · React 19 · Vite ·
Tailwind 4 · Recharts.

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

The backend currently runs on **Python 3.9, which is end-of-life**. Patched
releases of `python-multipart`, FastAPI, and Starlette all require Python
3.10+, so some dependency advisories cannot be resolved until the runtime
moves. This is the highest-priority item on the roadmap and is documented in
`docs/SECURITY.md §6`.

---

## Testing

```bash
cd backend && source .venv/bin/activate

python -m pytest tests/ -q                 # 98 tests
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
