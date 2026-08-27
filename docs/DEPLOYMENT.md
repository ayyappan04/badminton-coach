# Deployment guide

Getting ShuttleSense from a repository to a working application.

The architecture has three tiers that deploy **independently**, and that is
deliberate — but it does mean "deployed" is not one step. The frontend being
live does not make the app work; it needs an API, and the API needs Supabase.

| Tier | What runs there | Status |
|---|---|---|
| **Vercel** | static React SPA | ✅ deployed |
| **Supabase** | Postgres, Auth, Storage, Queues | ✅ provisioned |
| **Container host** | FastAPI API + Python worker | ⬜ **this is the remaining step** |

---

## 0 · Do you need a Docker MCP?

No. Claude Code has shell access, so with Docker Desktop installed it can run
`docker build`, `docker compose up` and `pytest` inside the image directly. An
MCP wrapper around the Docker CLI adds a layer without adding capability.

Docker is worth installing anyway — it is how you validate the image before
paying a host to find the problems for you.

---

## 1 · Validate locally

```bash
cd backend
docker build -t shuttlesense-api:latest -f Dockerfile .
```

Then run the suite **inside** the image. This is the step that catches a
dependency that resolves but does not work, and it is not the same as running
the tests on your laptop's Python:

```bash
docker run --rm \
  -e APP_ENV=development \
  -e JWT_SECRET=local-test-secret \
  -e DATABASE_URL=sqlite:////tmp/shuttlesense/test.db \
  -e STORAGE_DIR=/tmp/shuttlesense/storage \
  -v "$PWD/tests:/app/tests:ro" \
  shuttlesense-api:latest \
  python -m pytest tests/ -q
```

Expect **236 passed, 5 skipped**. The skips are files `.dockerignore`
deliberately excludes (`.git`, the frontend, `.env.example`); those same tests
run and pass outside the container, where the files exist.

Sanity-check the runtime contract too:

```bash
docker run --rm shuttlesense-api:latest sh -c 'python --version; id; ffmpeg -version | head -1'
```

You want Python 3.12, uid 1001 (**not** root), and ffmpeg present.

> **ffmpeg version note.** The image ships Debian bookworm's ffmpeg **5.1.9**.
> Everything the media pipeline does — probe, scale, fps cap, H.264, faststart,
> rotation baking — is verified working on it. If you develop against a newer
> ffmpeg, be aware that `-display_rotation` (used only to build a test fixture)
> does not exist before ffmpeg 6; the test fixture handles both.

---

## Which Supabase connection string to use

Supabase offers three, and the choice matters more than it looks. Find them
behind the **Connect** button at the top of the project, or under
**Project Settings → Database**.

| | Host | Port | Use for |
|---|---|---|---|
| **Direct** | `db.<ref>.supabase.co` | 5432 | **nothing, usually** |
| **Transaction pooler** | `aws-0-<region>.pooler.supabase.com` | 6543 | the **API** |
| **Session pooler** | `aws-0-<region>.pooler.supabase.com` | 5432 | the **worker**, and migrations |

The direct connection resolves to **IPv6 only**. Most managed hosts — Render's
free tier included — have no IPv6 egress, so it fails with:

```
connection to server at "2600:1f14:...", port 5432 failed: Network is unreachable
```

Nothing in that message mentions IPv6 or pooling, which is why it wastes an
afternoon. `/api/v1/ready` now recognises it and says so directly.

**Why the worker wants the session pooler rather than the transaction pooler:**
transaction mode returns the connection after every statement, which breaks
long transactions and the advisory state pgmq relies on. Session mode behaves
like a direct connection but over IPv4.

---

## 2 · Apply the database schema

Alembic owns the domain schema and **must run before any worker starts**. A
worker whose schema is missing tells you so at boot rather than looping:

```
ERROR  preflight check failed -> database schema incomplete (missing: …).
       Run `alembic upgrade head` against DATABASE_URL before starting workers.
```

Get the connection string from **Supabase → Project Settings → Database**.
Use the **direct** connection (port 5432) for migrations, not the pooler:

```bash
cd backend
export DATABASE_URL='postgresql+psycopg://postgres:PASSWORD@db.<ref>.supabase.co:5432/postgres'
python -m alembic upgrade head
```

Review before applying, if you prefer:

```bash
python -m alembic upgrade head --sql > schema.sql
```

Then the platform configuration — RLS, storage buckets, queues, Realtime:

```bash
supabase link --project-ref <ref>
supabase db push
```

> Already done for the `Badminton Coach` project: 10 migrations applied, 36
> tables with RLS, 3 private buckets, pgmq installed. Re-running is safe.

---

## 3 · Deploy the API and worker

They cannot run on Vercel — OpenCV and MediaPipe rule that out, which is the
whole reason the architecture puts them in containers. Pick a container host.

### Option 0 — worker on your own machine (start here)

The API is a control plane and costs almost nothing to host. The **worker** is
the expensive half: it decodes video and runs pose estimation, so it wants CPU
and several gigabytes of memory. Managed hosts charge accordingly, and there is
no free background-worker tier on Render.

So deploy the API, and run the worker locally at first:

```bash
cp deploy/worker.env.example deploy/worker.env   # fill in two values
./deploy/run-worker-local.sh
```

This exercises the entire production path — TUS uploads landing in Supabase
Storage, pgmq handing out jobs, signed playback URLs — for nothing. It is not a
permanent answer (close the laptop and queued matches wait), but it proves the
cloud wiring before you pay anyone to host it, and moving to a hosted worker
later is a config change, not a code change.

### Choosing a host

| Option | Monthly | Worker hosted | Cold starts | You maintain |
|---|---|---|---|---|
| Render free + local worker | **$0** | no — your machine | ~50s after idle | nothing |
| Render starter + worker | ~$32 | yes | no | nothing |
| **One VM** (2 vCPU / 4 GB) | **~€4–24** | yes | no | OS, TLS, restarts |
| Kubernetes | more | yes | no | a control plane |

**Kubernetes is the wrong answer here** and probably will be for a long time.
Two containers and one queue do not need an orchestrator; you would spend more
time operating the cluster than the application.

**A single VM is the best value** once the worker needs to run without your
laptop open. The expensive component is the worker — CPU and memory bound —
and VMs sell exactly that cheaply, whereas managed platforms charge a premium
for a background process. `deploy/vm/` makes it close to turnkey.

**Render is the fastest to a working URL**, and free if you run the worker
locally. Start here if you want it working today.

### Option A — Render (simplest, free)

The API is a control plane: it authorizes uploads, reads results and enqueues
jobs. No video byte passes through it, so it fits the free instance type with
room to spare — **85 MB resident against a 512 MB cap**.

That is only true because the CV stack is imported lazily. Importing
`app.main` used to pull in OpenCV, MediaPipe, matplotlib and Pillow — 374 MB
in a process that never decodes a frame, and 73% of the free tier before a
single request. `run_pipeline` and `court_detection` are now imported inside
the two functions that need them, so the worker still gets them on demand and
the API never pays for them.


`render.yaml` at the repo root defines both services. Render prompts once for
the secrets and never stores them in the file.

1. Render → **New → Blueprint** → select this repository.
2. Fill in when prompted:

   | Variable | Value |
   |---|---|
   | `SUPABASE_URL` | `https://<ref>.supabase.co` |
   | `SUPABASE_SERVICE_ROLE_KEY` | Supabase → Project Settings → **API Keys** → *Secret keys* → `default` → Reveal |
   | `DATABASE_URL` | pooler string, port **6543**, exactly as Supabase gives it |
   | `CORS_ORIGINS` | your Vercel URL, exactly, no trailing slash |

3. Deploy. The API gets a URL; the worker has no ingress, by design.

### Option B — Fly.io (more control over worker sizing)

`backend/fly.toml` defines one app with two process groups — same image,
different command.

```bash
cd backend
fly launch --no-deploy --copy-config
fly secrets set \
  SUPABASE_URL='https://<ref>.supabase.co' \
  SUPABASE_SERVICE_ROLE_KEY='...' \
  DATABASE_URL='postgresql+psycopg://...' \
  CORS_ORIGINS='https://your-app.vercel.app'
fly deploy
fly scale count api=1 worker=1
```

Scale the worker **out**, not up:

```bash
fly scale count worker=3
```

Raising `WORKER_CONCURRENCY` instead makes concurrent pipelines contend for the
same cores and the same frame-buffer budget, so they finish later than they
would in sequence.

### Option C — a single VM (best value once the worker must stay up)

Runs the API, the worker and automatic HTTPS on one box. Tested shape: Hetzner
CX22 or any 2 vCPU / 4 GB Ubuntu 24.04 instance.

**1. Point a domain at it.** Create an A record for `api.yourdomain.com` before
running anything — Caddy obtains its certificate over ACME, and without DNS it
retries in a loop.

**2. Prepare the machine:**

```bash
ssh root@YOUR_VM_IP
curl -fsSL https://raw.githubusercontent.com/ayyappan04/badminton-coach/main/deploy/vm/setup.sh | bash
```

That installs Docker, creates a non-root user to run the stack, restricts the
firewall to SSH and HTTP(S), enables unattended security updates, adds 2 GB of
swap, and installs a systemd unit so the stack survives a reboot.

**3. Configure and start:**

```bash
cp /opt/shuttlesense/deploy/vm/env.example /opt/shuttlesense/deploy/vm/.env
nano /opt/shuttlesense/deploy/vm/.env
systemctl start shuttlesense
```

Use the **direct** database connection (port 5432) here: the worker holds long
transactions and pgmq state that transaction-mode pooling breaks, and the API's
load on a single VM is trivial.

The API is never published to the host — only Caddy binds 80 and 443, and it
proxies over the internal Docker network. A firewall mistake cannot expose the
API without TLS.

```bash
systemctl restart shuttlesense                  # after a config change
docker compose -f /opt/shuttlesense/deploy/vm/docker-compose.vm.yml logs -f
```

Updating is `git pull && systemctl restart shuttlesense`.

**Memory matters more than cores.** On 4 GB keep `WORKER_MEMORY=3g` and
`MAX_ANALYSIS_FRAME_MB=900`, leaving headroom for the OS, Caddy and the API.
Set the frame budget too close to the container limit and a long match is
OOM-killed instead of degrading to a sparser sample rate.

### Whichever you pick

Verify before wiring the frontend to it:

```bash
curl https://<api-host>/api/v1/health    # {"status":"ok"}
curl https://<api-host>/api/v1/ready     # all checks true
```

`/ready` is the one that matters — it proves the API can actually reach
Postgres, Storage and the queue.

---

## 4 · Point the frontend at the API

In **Vercel → Settings → Environment Variables**:

| Variable | Value |
|---|---|
| `VITE_API_BASE_URL` | `https://<api-host>` (no trailing slash) |
| `VITE_SUPABASE_URL` | `https://<ref>.supabase.co` |
| `VITE_SUPABASE_ANON_KEY` | Supabase → Settings → API → `anon` / publishable |

Only these three. Anything else prefixed `VITE_` is shipped to every browser.

Redeploy for them to take effect — Vite inlines them at build time, so setting
a variable without rebuilding changes nothing.

> **Never** set `SUPABASE_SERVICE_ROLE_KEY` in Vercel. It bypasses Row Level
> Security completely; in a browser bundle it exposes every user's footage.
> `backend/tests/test_production_isolation.py` fails the build if it appears in
> client source or the built bundle.

---

### A note on `vercel.json`

It is validated against a strict schema **before** the build runs, and unknown
properties fail the deployment with *no build logs at all* — which looks
alarming and tells you nothing. Two consequences:

- Never add a `"//"` key as a pseudo-comment. Reasoning belongs here instead.
- The SPA rewrite must exclude `api/`:

  ```
  "source": "/((?!api/|assets/).*)"
  ```

  A true catch-all answers `/api/v1/*` with `index.html` and a **200**, so a
  missing backend looks like a working one returning HTML, and every API call
  fails as a JSON parse error at a call site that appears successful.

`backend/tests/test_vercel_config.py` asserts both.

---

## 5 · Make the site reachable

New Vercel projects enable **Deployment Protection**, which is why the URL
redirects to `vercel.com/sso-api`. To make it public:

**Vercel → Settings → Deployment Protection → Vercel Authentication → Disabled**

Leave it on if you want the site private during setup — the build is fine
either way.

---

## 6 · Supabase Auth settings

**Supabase → Authentication → URL Configuration**:

- **Site URL**: `https://your-app.vercel.app`
- **Redirect URLs**: add `https://your-app.vercel.app/verify-email` and
  `.../reset-password`

Without these, verification and password-reset links point at localhost.

Configure an SMTP sender under **Authentication → Emails** — the built-in one
is rate-limited and not for production.

---

## 7 · Verify end to end

```bash
cd backend
DATABASE_URL='...' SUPABASE_URL='...' SUPABASE_SERVICE_ROLE_KEY='...' \
  python manage.py doctor
```

Every check `ok`, and `warnings` empty. It warns specifically if a production
deployment is running on the local storage or job backends, both of which lose
data on restart.

Then, in the browser:

1. Sign up → verification email arrives.
2. Upload a match → progress advances, **and pausing actually pauses**.
3. Refresh mid-upload → it resumes rather than restarting.
4. Analysis completes → status moves `queued → normalizing → processing → analyzed`.
5. Video plays → check the network tab; the URL should be a **signed Supabase
   URL for `playback.mp4`**, not the original.
6. Delete the match → it disappears immediately.

```bash
python manage.py capacity     # realtime_factor, for sizing the fleet
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Vercel build runs `react-scripts` | Stale CRA framework preset | Already fixed by the root `vercel.json`; it overrides Project Settings |
| Deployment fails with **no build logs at all** | `vercel.json` failed schema validation before the build started | Vercel rejects unknown properties. JSON has no comments — never add a `"//"` key. `pytest tests/test_vercel_config.py` catches this |
| `/api/*` returns HTML with a 200 | SPA catch-all rewrite swallowing API paths | The rewrite must exclude `api/`: `/((?!api/\|assets/).*)` |
| Site 302s to `vercel.com/sso-api` | Deployment Protection | §5 |
| Banner: "Can't reach the ShuttleSense API" | `VITE_API_BASE_URL` unset/wrong, or CORS | Set it, redeploy, add the Vercel origin to `CORS_ORIGINS` |
| Browser console: CORS error | API doesn't list the Vercel origin | `CORS_ORIGINS` must match exactly — scheme, host, no trailing slash |
| Worker logs "database schema incomplete" | Migrations not run | §2 |
| Uploads start then 409 on complete | Storage RLS, or the bucket is missing | `supabase db push`; check the key's first segment is the user's uid |
| Videos stick in `queued` | No worker running, or it can't reach pgmq | `python manage.py queue`, then `stuck --requeue` |
| Analysis fails `ffmpeg_unavailable` | Wrong base image | `docker run --rm <image> ffmpeg -version` |
| `413` on upload initiation | File exceeds `MAX_VIDEO_GB` | Raise it, and check the Supabase plan's own limit |

Full runbook: **[OPERATIONS.md](OPERATIONS.md)**.
Architecture and rationale: **[PRODUCTION_ARCHITECTURE.md](PRODUCTION_ARCHITECTURE.md)**.

---

## What has been verified against live infrastructure

Not claims — measured against the real Supabase project.

| Path | Result |
|---|---|
| Secret key authenticates to Storage | ✅ both key formats work (`sb_secret_…` and legacy `service_role` JWT) |
| Buckets are private | ✅ all three, with correct size limits |
| Upload / stat / download / delete | ✅ byte-identical round trip, checksum verified |
| Signed read URL | ✅ 200 while valid |
| Signed URL **expires** | ✅ 400 after the TTL elapses |
| Unsigned public fetch | ✅ **refused** — the bucket really is private |
| **TUS resumable upload** | ✅ create → partial chunk → **resume from the server-reported offset** → byte-identical result |
| RLS cross-user isolation | ✅ user A cannot read user B's rows, or write their own pipeline fields |
| Storage path enforcement | ✅ own-prefix write allowed, foreign-prefix write refused |
| pgmq claim / lease / redelivery | ✅ second worker blocked while the lease holds; reclaimed after it expires |
| Container image on Python 3.12 | ✅ 236 tests pass inside it |

The resume test matters most: it sends half a file, reads the offset the server
reports, then continues from it in a fresh request — exactly what
`tus-js-client` does after a dropped connection. That is the behaviour the
whole large-upload design rests on.

**Still unverified:** the worker consuming pgmq over the public internet, which
needs `DATABASE_URL` (the database password). Everything it depends on is
verified individually; the composition is not.

---

## Cost shape

Video storage dominates. The design already limits it:

- Playback serves a **720p proxy**, not the original — most of the egress saving.
- Derived assets are versioned and immutable, so they cache hard at the CDN.
- Pose landmarks live in a gzipped artifact rather than as Postgres rows
  (~76× smaller; see [DATA_MODEL.md](DATA_MODEL.md)).
- Originals are retained until `manage.py retention` is run deliberately, and
  it refuses to delete one whose analysis proxy cannot be confirmed present.

The lever, once real usage exists, is `ORIGINAL_RETENTION_DAYS` plus
`RETAIN_ORIGINAL_ALWAYS=false`. Set a product policy before turning it on.
