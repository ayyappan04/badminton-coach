# Security model, testing, and known limitations

This document states what the application actually enforces today, how to
verify it yourself, and what is deliberately still open. It is written to be
checkable — every claim maps to a test in `backend/tests/`.

---

## 1. Authentication

**Approach: framework-native JWT auth (FastAPI + PyJWT + passlib/bcrypt).**

The project already had email/password auth before this review; the work here
hardened it rather than replacing it. A hosted provider (Supabase/Clerk/Auth0)
was considered and rejected for now because:

* the app is a self-contained FastAPI + SQLite/Postgres service with no
  existing third-party identity dependency, and adding one would move user
  PII to a new processor and complicate the consent/deletion guarantees in
  `PRIVACY_AND_CONSENT.md`;
* the credential surface here is small and now covered by tests;
* migration remains straightforward — auth is isolated behind
  `app/core/security.py` and `app/api/deps.py`.

If the product grows to need SSO, MFA, or social login, migrating to a
provider is the right call and is listed under next steps.

| Capability | Status | Where |
|---|---|---|
| Signup (email + password) | Implemented | `POST /api/v1/auth/register` |
| Login | Implemented | `POST /api/v1/auth/login` |
| Logout (server-side revocation) | Implemented | `POST /api/v1/auth/logout` |
| Email verification | Implemented | `POST /api/v1/auth/verify-email` |
| Resend verification | Implemented | `POST /api/v1/auth/resend-verification` |
| Password reset request | Implemented | `POST /api/v1/auth/request-password-reset` |
| Password reset | Implemented | `POST /api/v1/auth/reset-password` |
| Rate limiting | Implemented (in-process) | `app/core/rate_limit.py` |

**Password policy** (`app/core/security.py`): ≥10 characters, at least three
of {lowercase, uppercase, digit, symbol}, not a common password, not
containing the local part of the email, ≤72 bytes (bcrypt's real limit —
rejected rather than silently truncated).

**Session strategy.** Stateless JWT (HS256) with a 12-hour default lifetime.
Each token carries an `iat_ms` claim; each user row carries
`tokens_valid_from`. Logout and password reset set `tokens_valid_from = now`,
which invalidates every previously issued token. This gives real revocation
without a session table.

**Verification gating.** `REQUIRE_EMAIL_VERIFICATION` defaults to **true in
production** and false in development. When enabled, signup returns no session
token and login returns 403 until the address is verified.

**One-time tokens** (`app/core/tokens.py`): 256-bit random, stored only as a
SHA-256 hash, single-use, expiring (verification 24h, reset 30min). Issuing a
new token invalidates outstanding tokens of the same purpose.

**Account enumeration.** Login returns one identical 401 body for "no such
user" and "wrong password". Password reset returns one identical 200 body
whether or not the address exists. Signup necessarily reveals that an address
is taken (it must, to be usable) and is rate-limited to blunt that.

---

## 2. Authorization and data isolation

Ownership is enforced **server-side on every request**; UI filtering is never
relied on.

* `videos.owner_user_id` scopes every video and everything derived from it.
* `_get_owned_video()` in `app/api/videos.py` is the single choke point for
  per-video routes and returns **404** (not 403) for other users' videos, so
  the API does not confirm that an id exists.
* `GET /videos` filters by owner; `compare` requires ownership of *both* ids.
* The video **stream** route accepts the JWT as a query parameter (a `<video>`
  element cannot send an `Authorization` header) and resolves it through the
  same `resolve_user_from_token()` used by the normal dependency, including
  revocation checks.

**The one legitimate cross-user path** is a coach review: a student explicitly
invites a named coach to *one* video. While `status = "active"` the coach can
read that review and stream that file — nothing else. Revocation is immediate
and verified by test.

**Integration API keys** are read-only, scoped, revocable, and stored only as
SHA-256 hashes; the plaintext is shown exactly once at creation.

---

## 3. Upload hardening

`app/core/uploads.py`:

| Control | Implementation |
|---|---|
| Size limit | Enforced **while streaming** (`MAX_UPLOAD_MB`, default 200); partial file deleted on breach |
| Type allowlist | `.mp4 .mov .m4v .avi .webm` |
| Content validation | Container magic bytes (ISO-BMFF `ftyp`, `RIFF….AVI `, EBML) — a renamed `.elf`/`.html` is rejected |
| Empty files | Rejected |
| Stored filename | Server-generated UUID + allowlisted extension; the client filename never builds a path |
| Display filename | Normalised; path components, control characters (CR/LF), and `<>:"\|?*` stripped; length-capped |
| Path traversal | Destination resolved and asserted to be inside `UPLOADS_DIR` |
| Header injection | `FileResponse` sends **no** `Content-Disposition` filename |
| Rate limit / quota | `MAX_UPLOADS_PER_HOUR` (20) per user, `MAX_STORAGE_MB_PER_USER` (2048) |

**No shell is involved anywhere in video processing** — decoding is OpenCV's
Python API, so there is no ffmpeg command-line injection surface.

---

## 4. Transport and error hygiene

Applied by middleware in `app/main.py` to every response:
`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, a locked-down `Content-Security-Policy`
(`default-src 'none'`), `Permissions-Policy`, `Cache-Control: no-store`, and
HSTS in production. Interactive docs (`/docs`, `/openapi.json`) are disabled
in production.

CORS uses an explicit origin allowlist (never `*`) with restricted methods and
headers.

A catch-all exception handler logs the stack server-side and returns a
generic message, so tracebacks, file paths, and SQL never reach a client.

---

## 5. LLM / AI safety

**There is no LLM in the coaching path.** `app/services/coaching/coach_chat.py`
is intent-routed retrieval over the user's own database rows with fixed
templates. Classic prompt injection cannot alter control flow because there is
no model to instruct — user text only ever selects a handler.

That property is asserted rather than assumed:
`tests/test_injection_and_hardening.py` sends ten injection strings
(instruction override, secret solicitation, script tags, SQL, JNDI, template
syntax, traversal) and checks the answer never leaks configuration, never
echoes a script tag, and never returns attacker text verbatim.

**Injury and medical safety.** A keyword gate runs *before* intent routing, so
"sharp knee pain when I lunge" is never answered as a technique question. It
refuses to diagnose, tells the player to stop, and refers them to a
physiotherapist or sports doctor. This was a real gap found during this review
— the question previously routed to the "balance" coaching handler.

**If an LLM is added later**, the required controls are: treat all video
metadata/filenames/notes as untrusted data in a separate message from
instructions, never place secrets in the prompt, keep the injury gate ahead of
the model, and re-run these tests against the model-backed path.

---

## 6. Known limitations (honest list)

1. **Python 3.9 is end-of-life (October 2025) and blocks security patches.**
   The fixed releases of `python-multipart` (≥0.0.21), FastAPI (≥0.129) and
   Starlette (1.x) all require Python ≥3.10. `pip-audit` therefore still
   reports advisories that cannot be resolved on this runtime. **Upgrading to
   Python 3.11+ is the single highest-value security action available.**
2. **Rate limiting is in-process.** Correct for one instance; a multi-worker
   or multi-replica deployment needs Redis or an edge/WAF limit.
3. **Tokens are stored in `localStorage`** on the frontend, which is readable
   by any successful XSS. Mitigated by React's default escaping, a strict CSP,
   and no `dangerouslySetInnerHTML` anywhere in the codebase — but
   `HttpOnly; Secure; SameSite` cookies plus CSRF tokens would be strictly
   better.
4. **No malware scanning** of uploaded files. Files are never executed and are
   only opened by OpenCV, but ClamAV (or an equivalent) in the ingest path is
   recommended before accepting untrusted public uploads.
5. **Storage is a local filesystem directory.** There are no public URLs and
   every read is authenticated, but a production deployment should move to
   object storage with private buckets and short-lived signed URLs.
6. **Processing runs in an in-process thread pool** (`app/worker.py`).
   Videos longer than `MAX_VIDEO_DURATION_S` (30 min) are rejected before any
   decoding, which bounds the obvious abuse, but there is still no wall-clock
   kill for a decode that hangs on a malformed-but-short file. Python threads
   cannot be pre-empted, so a real fix means moving processing to a separate
   process (or Celery worker) that can be terminated — see next steps.
7. **No MFA, no SSO, no password-breach corpus check.**
8. **Analysis quality itself is a separate axis** from security — see
   `V2_DESIGN.md §18` for what the CV pipeline can and cannot reliably do.

---

## 7. How to verify all of this

```bash
cd backend
source .venv/bin/activate

# Full suite: auth, authorization/isolation, upload hardening, injection
python -m pytest tests/ -q

# Live end-to-end against a real server
uvicorn app.main:app --port 8131          # terminal 1
python -m tests.smoke_live                # terminal 2

# Badminton scenario matrix through the real CV pipeline
python -m tests.run_video_matrix

# Security scans
pip install pip-audit bandit
pip-audit
bandit -r app/ -ll

# Frontend
cd ../frontend && npm audit && npx tsc -b --noEmit && npm run lint && npm run build
```

## 8. Test accounts

Created on demand by the test fixtures with random `@example.com` addresses
(RFC 2606 reserved — not routable, so no mail can escape). The demo seed
script uses `arun.demo@example.com` / `priya.demo@example.com` with password
`testpass123`; these are **local demo data only** and must never exist in a
deployed environment.
