# Production architecture

> Large bytes move directly through object storage. Persistent state lives in
> Postgres. Durable queues coordinate work. Heavy computation runs in dedicated
> workers. Vercel serves the application, not the video pipeline.

---

## 1 · Topology

```
                         ┌─────────────────────────┐
                         │        Browser          │
                         │  React / Vite (Vercel)  │
                         └────────────┬────────────┘
                                      │
              small JSON control-plane calls   │   video bytes (TUS, resumable)
                     ┌────────────────┴────────┴────────────────┐
                     ▼                                          ▼
          ┌──────────────────────┐                   ┌──────────────────────┐
          │  Vercel (static SPA) │                   │  Supabase Storage    │
          │  + edge rewrites     │                   │  video-originals     │
          └──────────┬───────────┘                   │  video-derived       │
                     │ /api/*                        │  avatars  (private)  │
                     ▼                                └───────────┬──────────┘
          ┌──────────────────────┐                                │
          │  FastAPI API         │                                │
          │  (container)         │  control plane only            │
          │  63 + 9 endpoints    │  never a data pipe             │
          └──────────┬───────────┘                                │
                     │                                            │
              ┌──────▼────────────────────────────────────────────▼───────┐
              │                       Supabase                            │
              │  Auth · Postgres 17 · RLS · Storage metadata              │
              │  pgmq queues · Realtime · processing state                │
              └────────────────────────┬─────────────────────────────────┘
                                       │ durable queued jobs (pgmq)
                                       ▼
                        ┌──────────────────────────────┐
                        │  Python Video Worker         │
                        │  (container, scale to N)     │
                        │  FFmpeg · OpenCV · MediaPipe │
                        │  ShuttleSense CV pipeline    │
                        └──────────────┬───────────────┘
                                       │
                    ┌──────────────────┴──────────────────┐
                    ▼                                     ▼
           Supabase Storage                        Supabase Postgres
           derived assets                          analytics / results
```

**Video bytes take exactly two paths, and neither touches Vercel or the API:**

```
browser  ──TUS──▶  Supabase Storage          (upload)
storage  ──HTTP──▶ worker local temp dir     (processing)
storage  ──CDN──▶  browser, signed URL       (playback)
```

## 2 · Service responsibilities

| Service | Owns | Explicitly does not |
|---|---|---|
| **Vercel** | Static SPA, edge caching, `/api/*` rewrite | Video bytes, CV work, durable state |
| **FastAPI container** | Auth checks, upload authorization, upload verification, job enqueue, read APIs | Receiving or serving video bytes |
| **Worker container** | ffprobe, ffmpeg, the 14-stage CV pipeline, writing results | Serving HTTP; holding permanent state on disk |
| **Supabase Postgres** | All persistent state; RLS as the last line of defence | Storing video or per-frame arrays |
| **Supabase Storage** | Originals, proxies, stills, analysis artifacts | Being public, ever |
| **Supabase Auth** | Identity, credentials, verification, reset | Application profile data |
| **pgmq** | Distributing work, visibility timeouts, dead-lettering | Being the source of truth for user-visible state |

## 3 · Architecture decision: why the API stayed Python

Two options were on the table.

**Option A — Vercel hosts the frontend; FastAPI remains the API as an independent container.**
**Option B — Vercel API routes become the control plane; Python shrinks to a CV worker.**

**Option A was chosen.** The reasoning:

- The existing API is ~6,700 lines of Python across 63 endpoints, and a large
  share of it — technique scorecards, match analytics, coach chat retrieval,
  the player profile builder — is *domain logic that reads CV output*. Option B
  means porting all of it to TypeScript, or splitting it across two languages
  at an arbitrary seam.
- That port buys nothing a user can perceive. It is pure rewrite risk against a
  test suite that currently proves the behaviour is correct.
- The heavy read endpoints (`/scorecards`, `/heatmap`, `/overlay-manifest`)
  reconstruct NumPy structures from database rows. In TypeScript they would be
  a reimplementation of numeric code that already agrees with the pipeline.
- Vercel functions cannot run OpenCV or MediaPipe, so Python remains in the
  topology regardless. Option B produces two backends rather than one.

What Option A gives up is a single deployment target. That is a real cost, and
it is paid with one extra container and one DNS record — cheap next to a
rewrite of the analytical core.

**What did move to Vercel:** the frontend, edge caching, and TLS. **What moved
to Supabase:** identity, persistence, object storage, queues and Realtime.
**What stayed Python:** everything that reads or writes analysis.

## 4 · Upload flow

```
 1. POST /videos/uploads
       ├─ authenticate
       ├─ enforce quota (active uploads, storage, daily jobs, file size)
       ├─ create videos row               status = created
       ├─ allocate immutable object key   {user_id}/{video_id}/original.{ext}
       ├─ create upload_sessions row
       └─▶ { video_id, bucket, object_path, upload_method: "tus", endpoint }
              ↑ coordinates, NOT a credential

 2. browser ──TUS 6 MiB chunks──▶ Supabase Storage
       ├─ authenticated with the user's OWN Supabase session
       ├─ Storage RLS: (storage.foldername(name))[1] = auth.uid()
       ├─ pause / resume / retry / cancel
       └─ fingerprinted, so a refresh resumes instead of restarting

 3. POST /videos/uploads/{id}/complete
       ├─ storage.stat()  ── object really exists?
       ├─ size matches what was declared?   (catches truncated uploads)
       ├─ videos.status = uploaded
       ├─ video_assets row for the original
       ├─ storage_usage incremented
       ├─ analysis_runs row created
       └─ pgmq.send()  ── in the SAME transaction as the run row
```

Step 3's final two operations share one Postgres transaction, which is the
whole reason pgmq was chosen over an external broker: "run created" and "job
queued" commit together or not at all. That removes the atomicity gap an
**outbox pattern** would otherwise exist to cover, so the outbox was
deliberately not built. If the queue ever moves out of Postgres, the outbox
becomes necessary again.

## 5 · Processing flow

```
worker.receive(visibility_timeout = JOB_LEASE_S)
   └─ claim_run()  ── atomic UPDATE ... WHERE status='pending'
                      OR lease_expires_at < now()
        │  zero rows = another worker owns it → retry later
        ▼
   Heartbeat thread extends the lease every JOB_HEARTBEAT_S
        │
        ├─ ensure_media_assets()
        │    ├─ reuse a fresh analysis proxy if one exists (skip re-transcode)
        │    ├─ download original → per-run temp dir
        │    ├─ ffprobe → authoritative metadata
        │    ├─ validate against production limits
        │    ├─ sha256 (streamed)
        │    ├─ ffmpeg → analysis proxy   (1080p / 60fps / CRF 18)
        │    ├─ ffmpeg → playback proxy   (720p / 60fps / CRF 26 / faststart)
        │    ├─ ffmpeg → poster + thumbnail
        │    └─ upload derived assets, record rows, account bytes
        │
        ├─ run_pipeline()  ── the existing 14 CV stages, unchanged
        ├─ persist results  ── calibration, tracks, poses, rallies, shots, insights
        ├─ publish pipeline_result.json.gz to object storage
        │     (so finalize_after_identity survives a worker restart)
        │
        └─ mark run SUCCEEDED + is_current, ack the message
   temp dir removed, whether or not the run succeeded
```

**Progress** is stage-level, not a fabricated linear percentage. Stages with
unpredictable duration report their stage name; the percentage moves at real
stage boundaries.

## 6 · Failure recovery

| Failure | What happens |
|---|---|
| Worker SIGKILLed mid-analysis | Heartbeat stops → lease expires → `requeue_stalled` returns the run to `pending` and re-enqueues. Attempt counter increments. |
| Worker redeployed | SIGTERM → finishes the current message, then exits. Nothing is abandoned. |
| Duplicate queue delivery | `claim_run` finds the run `SUCCEEDED` → message acked, no second pipeline. |
| Transient storage/DB error | Job returns RETRY → `nack` with exponential backoff (15s → 300s). |
| Poisoned message | After `JOB_MAX_ATTEMPTS` deliveries → dead-letter queue, kept for inspection. |
| Corrupt/unsupported media | Permanent error code, `retryable=false`, video → `failed` with a safe message. No retry loop. |
| Vercel redeploy | Irrelevant. Vercel holds no job state. |
| Browser closed | Irrelevant. All state is server-side. |
| Postgres briefly unavailable | API `/ready` reports degraded; queue messages stay queued; worker retries. |

## 7 · Storage model

```
video-originals/                       private, immutable, no UPDATE policy
  {user_id}/{video_id}/original.{ext}

video-derived/                         private, reproducible, cached hard
  {user_id}/{video_id}/{transform_version}/
      analysis.mp4        playback.mp4        poster.jpg        thumbnail.jpg
      clips/{clip_id}.mp4
  {user_id}/{video_id}/{pipeline_version}/
      overlays/manifest.json
      artifacts/pipeline_result.json.gz

avatars/                               private, separate policy
  {user_id}/...
```

The **first path segment is the authorization boundary**, not a naming
convention. `app/storage/paths.py` refuses any segment it did not generate, and
Storage RLS independently checks `(storage.foldername(name))[1] = auth.uid()`.
The user's filename is display metadata only; it never reaches a key.

**Versioning:** media assets carry `MEDIA_TRANSFORM_VERSION`; overlays and
analysis artifacts carry the pipeline version. Changing a normalization
parameter makes existing proxies detectably stale rather than silently wrong.

## 8 · Media profiles, and why they differ

| | Analysis proxy | Playback proxy |
|---|---|---|
| Resolution cap | 1920×1080 | 1280×720 |
| Frame rate cap | 60 | 60 |
| CRF | **18** | 26 |
| Audio | stripped | AAC 128k |
| Optimised for | predictable decoding, motion fidelity | egress cost, browser seeking |

The analysis profile is conservative on purpose. Badminton is close to the
worst case for video compression: the shuttle is a handful of pixels moving
faster than any other racket-sport projectile, and limbs at contact are pure
motion blur. Tuning the CV input for file size does not make the analysis fail
visibly — it makes shuttle detection quietly find less, and every downstream
number is then confidently wrong. That is worse than an error.

**Passthrough:** a source already H.264/yuv420p inside the analysis envelope is
remuxed with `+faststart` rather than re-encoded — no generation loss, and a
4 GB file finishes in seconds.

**Rotation** is baked into pixels and the tag cleared, because `cv2` does not
apply a display matrix. Without this, every portrait phone upload would be
analyzed sideways.

**Client-side transcoding was rejected** as the primary architecture: it pins a
phone's CPU for minutes, allocates the file in WASM memory, thermally
throttles, and produces nothing until it finishes — so closing the tab uploads
zero bytes. The browser does a metadata-only preflight and nothing more.

## 9 · Authentication

Supabase Auth owns identity in production. `AUTH_MODE` selects the posture:

| Mode | Accepts | Use |
|---|---|---|
| `legacy` | this app's HS256 tokens | local dev, tests, pre-cutover |
| `supabase` | Supabase tokens only | production |
| `dual` | both | the cutover window |

Verification prefers **asymmetric** ES256/RS256 against the project's published
JWKS, so no shared secret sits in the API process at all; HS256 against
`SUPABASE_JWT_SECRET` is the fallback for projects on a legacy key.

**A profile row's primary key IS the Supabase user id.** That single choice is
what lets one value serve as `videos.owner_user_id`, as `auth.uid()` inside an
RLS policy, and as the first segment of every storage key — so the three
enforcement layers cannot drift apart.

In `supabase` mode the local credential endpoints (`/auth/register`,
`/auth/login`, `/auth/reset-password`, …) return **410 Gone**. Two password
stores means an account can be taken over through whichever is weaker.

## 10 · Security boundaries

```
┌─ PUBLIC ────────────────────────────────────────────────────┐
│ VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY, VITE_API_BASE_URL │
│ Shipped to every browser. Assume they are published.         │
└──────────────────────────────────────────────────────────────┘
┌─ TRUSTED SERVER ────────────────────────────────────────────┐
│ SUPABASE_SERVICE_ROLE_KEY   bypasses RLS entirely            │
│ DATABASE_URL                                                 │
│ JWT_SECRET (legacy), METRICS_TOKEN                           │
│ API container · worker container · CI secrets. Nowhere else. │
└──────────────────────────────────────────────────────────────┘
```

Four independent layers must all agree before one user reads another's match:

1. **Supabase Auth** — a verified token.
2. **Application ownership checks** — `_get_owned_video`, 404 not 403.
3. **Postgres RLS** — `videos_select_own`, `private.can_read_video()`.
4. **Storage RLS** — the object key's owner prefix.

Clients may `SELECT` their own rows and nothing else. There is **no** client
INSERT/UPDATE/DELETE policy on any domain table: processing state, analysis
confidence, pipeline results and ownership are decided by the pipeline. RLS
denies by default, so the *absence* of a write policy is the enforcement.

Seven server-only tables (`api_keys`, `one_time_tokens`, `training_assets`,
`consent_records`, `annotations`, `processing_jobs`, `alembic_version`) have
RLS enabled with **zero** policies — total denial to every client role. The
Supabase linter reports these at INFO level; that finding is the intended state.

## 11 · Migration ownership

| Owner | Owns | Location |
|---|---|---|
| **Alembic** | Domain tables, columns, indexes, check constraints | `backend/alembic/versions/` |
| **Supabase SQL** | RLS + policies, storage buckets + policies, pgmq, Realtime, DB functions | `supabase/migrations/` |

Neither system defines an object the other owns. Alembic runs **first** because
a policy needs its table to exist. The SQL applied to the hosted project was
generated by `alembic upgrade head --sql`, so there is exactly one authority
for the schema and no hand-maintained second copy.

## 12 · Deployment topology

```
app.shuttlesense.com   →  Vercel        (static SPA, edge cache)
api.shuttlesense.com   →  API container (1–N, stateless, horizontally scalable)
                          worker containers (1–N, no ingress)
<ref>.supabase.co      →  Postgres, Auth, Storage, Queues, Realtime
```

Environments are separate Supabase projects. A Vercel preview deployment must
never point at production data; preview builds carry the staging project's
`VITE_*` values.

Connection pooling: the API uses the **session pooler** (port 6543, transaction
mode) because containers scale horizontally; the worker and migrations use the
**direct** connection (5432) because they hold long transactions and pgmq
advisory state.

## 13 · Environment variables

See `.env.example` for the annotated list. The three that change behaviour most:

| Variable | Values | Effect |
|---|---|---|
| `STORAGE_BACKEND` | `local` \| `supabase` | Filesystem vs. private buckets |
| `JOB_BACKEND` | `local` \| `pgmq` | Thread pool vs. durable queue |
| `AUTH_MODE` | `legacy` \| `supabase` \| `dual` | Which token issuers are trusted |

All three default to the local implementations so `pytest` and `uvicorn` work
with no environment set. `python manage.py doctor` warns if a production
deployment is running on any of them.

## 14 · Observability

Every log line carries `request_id`, `video_id`, `analysis_run_id`, `job_id`,
`user_id` and `worker_id` where known, so one video id reconstructs the whole
story across two containers that never spoke to each other. Tokens, keys and
signed URLs are redacted structurally — including nested in dicts — rather than
by remembering not to log them.

`GET /api/v1/metrics` exposes counters, gauges and timing percentiles
(uploads started/completed/failed, uploaded bytes, normalization and analysis
duration, queue wait, failures by stage, retries, dead letters, stale leases
reclaimed). In production it requires `METRICS_TOKEN`.

`/api/v1/health` is liveness only — deliberately dependency-free, so a database
blip does not make an orchestrator kill a healthy process. `/api/v1/ready`
checks database, storage and queue with one cheap round trip each.
