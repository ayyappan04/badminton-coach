# Badminton Coach — Project Validation and Security Report

**Repository:** https://github.com/ayyappan04/badminton-coach
**Reviewed at:** `3b982c9` → **delivered at `38569fa`**
**Scope:** local development app and repository code only. No third-party
system was tested, no footage was scraped, and no email was sent to a real
address.

---

## 1. Executive summary

### Correction to the brief's premise

The brief stated *"the project currently does not have authentication."*
**That is not accurate, and I did not build on it.** Inspection found a
complete JWT email/password implementation already present:

| Component | File | Evidence |
|---|---|---|
| Password hashing | `backend/app/core/security.py` | passlib/bcrypt, `$2b$` hashes verified in DB |
| Token issue/verify | `backend/app/core/security.py` | HS256 JWT |
| Auth dependency | `backend/app/api/deps.py` | `get_current_user` |
| Signup / login / me | `backend/app/api/auth.py` | 3 routes |
| Per-user ownership | `backend/app/api/videos.py` | `_get_owned_video()` |

A route-by-route enumeration of the running app measured **60 of 66 endpoints
already requiring authentication**, 2 using API keys, and 4 public
(login, register, health, and the video stream — which did its own manual
token check). Cross-user isolation was already working: all 26 authorization
tests I wrote passed against the *unmodified* code.

So the job became **verify, find the real gaps, and harden** — not "add auth".
That is what this report covers.

### Current status

Working, tested, and hardened. Backend runs, frontend builds, analysis
pipeline completes.

| Measure | Before | After |
|---|---|---|
| Automated tests | 0 | **98 passing** |
| Live end-to-end checks | 0 | **35 passing** |
| Test baseline pass rate | 71/93 | **98/98** |
| Frontend npm advisories | 4 high | **0** |
| Backend high/medium SAST findings | — | **0** (4 low, all reviewed as acceptable) |

### What was added

Server-side logout, email verification, password reset, rate limiting,
password policy, upload content-validation and quotas, security headers, a
medical-safety gate in the coach, a 98-test suite, a live smoke harness, a
14-scenario badminton video matrix, CI, `.env.example`, and `docs/SECURITY.md`.

### Highest-risk findings

| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | **Critical** | `JWT_SECRET` fell back to the literal `"dev-secret-change-in-production"`. Anyone reading the public repo could forge a token for any account. | **Fixed** |
| 2 | **High** | No upload size limit — `shutil.copyfileobj` streamed unbounded to disk. | **Fixed** |
| 3 | **High** | No content validation — any file renamed `.mp4` was stored as a video. | **Fixed** |
| 4 | **High** | Logout was client-side only; tokens stayed valid 7 days. Password reset did not exist. | **Fixed** |
| 5 | **High** | Python 3.9 is EOL and blocks dependency security fixes. | **Open — needs runtime upgrade** |
| 6 | **Medium** | Injury/pain questions were answered as technique coaching. | **Fixed** |
| 7 | **Medium** | `python-jose` → `ecdsa` Minerva timing advisory, no fix available. | **Fixed** (swapped to PyJWT) |
| 8 | **Medium** | No rate limiting anywhere; no password policy. | **Fixed** |
| 9 | **Medium** | No security headers; unhandled errors could leak tracebacks. | **Fixed** |
| 10 | **Low** | User-controlled filename echoed into `Content-Disposition`. | **Fixed** |

### Recommended next steps (top 3)

1. **Upgrade to Python 3.11+** — unblocks `python-multipart` ≥0.0.21, FastAPI
   ≥0.129, Starlette 1.x and clears most remaining advisories.
2. **Validate the CV pipeline on real badminton footage.** Pose, tracking, and
   stroke recognition are **not validated** — synthetic clips cannot exercise
   them (see §5 and §11).
3. **Move sessions to `HttpOnly; Secure; SameSite` cookies** and processing to
   a killable subprocess.

---

## 2. Project architecture

**Stack:** FastAPI 0.111 + SQLAlchemy 2.0 + SQLite (dev) / Postgres (prod
ready) · React 19 + TypeScript + Vite + Tailwind 4 · OpenCV 4.10 + MediaPipe
0.10 · Python 3.9, Node 22, npm.

```
backend/app/
  api/          9 routers  (auth, videos, profile, technique, community,
                            consent, coach, coach_reviews, integration)
  core/         config, security, deps ── NEW: mailer, tokens, rate_limit, uploads
  models/       15 SQLAlchemy model modules
  services/
    cv_pipeline/    14 stages (quality → court → tracking → pose → shuttle →
                    rally → phases → shots → biomechanics → tactics → overlay)
    coaching/       insight_generator, technique_scores, coach_chat
    tactics/        match_analytics, doubles_rotation
    profiling/      player_profile_builder
  worker.py     in-process ThreadPoolExecutor
frontend/src/   4 pages + 26 components ── NEW: AccountFlows.tsx
```

**Data flow.** Upload → validate (§8) → store under UUID name → enqueue →
pipeline stages persist rows as they complete → dashboard reads rebuild from
persisted rows (restart-safe).

**Auth flow.** `register` → bcrypt hash + verification token emailed →
`verify-email` → `login` → HS256 JWT (`sub`, `exp`, `iat_ms`) → every request
resolves through `resolve_user_from_token()`, which rejects tokens issued
before `users.tokens_valid_from` (bumped by logout and password reset).

**Storage flow.** Local filesystem at `STORAGE_DIR`, never web-served. All
reads go through authenticated `GET /videos/{id}/stream`, which re-resolves
the token, checks ownership (or an active coach review), and asserts the
resolved path is inside `UPLOADS_DIR`.

**AI/LLM:** **none.** The coach is deterministic retrieval + templates over
the user's own DB rows. Confirmed by grep — no LLM SDK anywhere.

---

## 3. Setup results

Fresh clone into `/tmp/bc-fresh`, isolated venv:

```bash
git clone https://github.com/ayyappan04/badminton-coach.git app   # CLONE_OK 3b982c9
python3 -m venv .venv-test
./.venv-test/bin/pip install -r backend/requirements.txt          # exit 0
./.venv-test/bin/python -c "import fastapi, cv2, mediapipe, sqlalchemy, jose, passlib"  # IMPORTS_OK
```

| Question | Answer |
|---|---|
| Installs cleanly? | **Yes** — fresh clone + venv, exit 0 |
| App starts? | **Yes** — uvicorn, `/health` 200 |
| Homepage loads? | **Yes** — Vite dev server + production build (221 ms) |
| Video upload works? | **Yes** — verified live, real MP4 |
| Analysis starts / completes? | **Yes** — reached `analyzed` in ~4 s for a 6 s clip |
| Results displayed? | **Yes** — quality-report/rallies/phases/insights all 200 |
| Errors handled clearly? | **Yes** — e.g. *"No players could be reliably detected in this video. Try a clearer, more direct camera angle."* |
| Works on a fresh environment? | **Yes** |

**Setup issues found and fixed:** no `.env.example` (added); no test
infrastructure (added); `*.db` correctly gitignored and no DB committed.
Migrations: none needed — `Base.metadata.create_all()` at startup; new
columns are additive and SQLite tolerates them on a fresh DB. *A real
deployment should adopt Alembic — noted in §12.*

---

## 4. Functional test results

Full suite: `cd backend && python -m pytest tests/ -q` → **98 passed**.
Live: `python -m tests.smoke_live` → **35 passed, 0 failed**.

| Test | Steps | Expected | Actual | Result |
|---|---|---|---|---|
| Homepage / health | GET `/api/v1/health` | 200 + headers | 200, nosniff/DENY/CSP present | **Pass** |
| Frontend build | `tsc -b && vite build` | clean | typecheck OK, built 221 ms | **Pass** |
| Navigation | 4 pages + 3 new account routes | render | typecheck + build clean | **Pass** |
| Upload (valid mp4) | POST real MP4 | 200 | 200 | **Pass** |
| Analysis starts | POST `/process` | queued | `{"status":"processing"}` | **Pass** |
| Analysis completes | poll `/status` | terminal state | `analyzed` in 4 s | **Pass** |
| Results display | 4 result endpoints | 200 | all 200, quality 84 | **Pass** |
| Invalid upload (.txt) | POST text/plain | 400 | 400 | **Pass** |
| Empty file | POST 0 bytes | 400 | 400 | **Pass** |
| Corrupted video | truncated MP4 | no 500 | handled, no 500 | **Pass** |
| Non-video renamed .mp4 | ELF + HTML bodies | 400 | 400 both | **Pass** |
| Oversized upload | > `MAX_UPLOAD_BYTES` | 413, no partial file | 413, upload dir unchanged | **Pass** |
| Unsupported format | `.txt`, unknown ext | 400 | 400 | **Pass** |
| Multiple uploads | 25 sequential | quota enforced | 429 after limit | **Pass** |
| Processing failure | synthetic clip, no humans | clear message, not a crash | clear message, `analyzed` | **Pass** |
| Page refresh during processing | poll `/status` after restart | state from DB | status persists | **Pass** |
| API failure handling | 4 error probes | no 500, no leakage | no 500, no traceback/path | **Pass** |
| Mobile viewport | — | — | **Not tested** — see §11 | — |
| Slow network | — | — | **Not tested** — see §11 | — |

Evidence: `docs/evidence/baseline-pytest.txt`, `backend/tests/`.

---

## 5. Badminton video test results

**Sourcing decision.** The brief forbids scraping and downloading copyrighted
footage. No licensed corpus is bundled with the repo, and I was given no user
clips. So I **generated 14 test clips locally** with OpenCV
(`backend/tests/video_scenarios.py`) — lawful, reproducible, and committed.
No BWF, YouTube, or Reddit content was accessed.

**This is a real limitation, stated plainly:** synthetic clips of coloured
rectangles validate the *plumbing* (quality gate, court detection, calibration
fallback, rally segmentation, error handling, latency) but **cannot** validate
pose estimation, player tracking, or stroke recognition, which need genuine
human bodies. Those rows are marked NOT TESTED rather than guessed.

Measured by `python -m tests.run_video_matrix` (pipeline v2.0.0), full JSON in
`docs/evidence/video-matrix.json`:

| Scenario | File | Quality | Court conf | Tracks | Rallies | Shots | Latency | Verdict |
|---|---|---|---|---|---|---|---|---|
| Singles rally | `singles_rally.mp4` | 84 | 0.71 | 4 | 2 | 0 | 0.6× RT | Plumbing pass |
| Doubles rally | `doubles_rally.mp4` | 84 | 0.71 | 6 | 1 | 0 | 0.7× RT | Plumbing pass |
| Low light | `low_light.mp4` | **52** | 0.15 → fallback | 1 | 0 | 0 | 0.5× RT | **Pass** — degraded correctly, `needs_user_calibration` |
| Motion blur | `motion_blur.mp4` | **60** | 0.60 | 2 | 1 | 0 | 0.6× RT | **Pass** — flagged |
| Camera shake | `camera_shake.mp4` | 79 | 0.85 | 2 | 1 | 0 | 0.6× RT | Pass |
| Camera cuts | `camera_cuts.mp4` | 81 | 0.71 | 4 | 1 | 0 | 0.6× RT | **Pass** — 2 cuts detected, tracking reset, advice given |
| Partial court | `partial_court.mp4` | 84 | 0.66 | 0 | 0 | 0 | 0.5× RT | **Partial** — quality not lowered |
| Portrait phone | `portrait_phone.mp4` | 84 | 0.69 | 3 | 1 | 0 | 0.6× RT | **Partial** — orientation not flagged |
| Landscape phone | `landscape_phone.mp4` | 78 | 0.72 | 2 | 1 | 1 | 0.4× RT | Pass |
| Low resolution 426×240 | `low_resolution.mp4` | **71** | 0.73 | 0 | 0 | 0 | 0.1× RT | **Partial** — shuttle correctly skipped, but 71 over-rates unusable footage |
| Low frame rate 8 fps | `low_framerate.mp4` | 79 | 0.71 | 3 | 0 | 0 | 0.4× RT | Pass — flagged |
| Multiple people | `multiple_people.mp4` | 84 | 0.71 | 4 | 1 | 0 | 0.6× RT | Pass |
| Player occlusion | `occlusion.mp4` | 84 | 0.71 | **0** | 0 | 0 | 0.5× RT | **Fail** — crossing players defeat the tracker |
| Non-badminton footage | `no_court.mp4` | **53** | 0.15 → fallback | 0 | 0 | 0 | 0.5× RT | **Pass** — refused to hallucinate a court |

Serve / smash / clear / drop / net shot / defensive lift, broadcast angle, and
side-angle training footage: **NOT TESTED** — all require real footage.

### Scores (rubric 0–5)

| Dimension | Score | Basis |
|---|---|---|
| Upload handling | **5** | Every malformed-input test passes; streaming cap, magic bytes, quotas |
| Video processing | **4** | 14/14 scenarios completed without crashing; graceful degradation |
| Pose / keypoint detection | **Not scored** | 0 poses on synthetic input — needs real footage |
| Player tracking | **2** | 0 tracks under occlusion, partial court, and low resolution — classical HOG limits confirmed |
| Stroke recognition | **Not scored** | 1 shot across 14 clips; depends on pose, untestable here |
| Coaching feedback | **4** | Deterministic, evidence-linked, confidence on every claim |
| **Safety of coaching advice** | **5** | Refuses diagnosis, refers to physio, refuses "train through pain" |
| UI / UX | **4** | Builds clean, dark theme, clear error copy; not re-screenshotted this pass |
| Performance | **5** | 0.1×–0.7× realtime on CPU |
| **Overall confidence** | **3** | Infrastructure and safety strong; ML quality unvalidated on real footage |

**Does the app overclaim?** No. Every scenario returned explicit limitation
tags (`no_players_detected`, `needs_user_calibration`,
`shuttle_not_reliably_detected`), the court detector fell back rather than
inventing geometry, and confidence accompanies every derived number.

**One honesty gap found:** the shuttle detector emitted **170 "shuttle points"
on non-badminton footage** and 213 under occlusion — a motion-blob heuristic
latching onto any moving object. Confidence is capped at ≤0.5 and the UI
labels it experimental, but the false-positive rate is higher than the label
implies. Logged in §12 (High).

---

## 6. Authentication implementation

**Chosen: framework-native JWT (FastAPI + PyJWT + passlib/bcrypt)** — hardening
the existing implementation rather than replacing it.

**Why not a hosted provider.** A Supabase/Clerk/Auth0 migration would move user
PII to a new processor, which conflicts with the deletion and consent
guarantees already documented in `PRIVACY_AND_CONSENT.md` and implemented in
`DELETE /account`. The credential surface here is small and now test-covered,
and auth is isolated behind two modules, so migrating later stays cheap. If
SSO/MFA becomes a requirement, a provider is the right call — recorded in §12.

**Files changed:** `core/config.py`, `core/security.py`, `api/deps.py`,
`api/auth.py`, `models/user.py`, `main.py`.
**New:** `core/mailer.py`, `core/tokens.py`, `core/rate_limit.py`,
`core/uploads.py`, `frontend/src/pages/AccountFlows.tsx`.

**New routes:** `POST /auth/logout`, `/auth/verify-email`,
`/auth/resend-verification`, `/auth/request-password-reset`,
`/auth/reset-password`. **New pages:** `/forgot-password`, `/reset-password`,
`/verify-email` (public by design).

**Session strategy.** Stateless HS256 JWT, 12 h default (was 7 days). Each
token carries `iat_ms`; each user carries `tokens_valid_from`. Logout and
password reset set it to now, revoking every outstanding token — real
revocation without a session table.

**Email verification.** One-time 256-bit token, SHA-256 at rest, 24 h expiry,
single-use, superseded on reissue. `REQUIRE_EMAIL_VERIFICATION` defaults
**true in production**: signup returns no token and login returns 403 until
verified. Verified by subprocess test.

**Password reset.** 30-minute single-use token; identical 200 response whether
or not the account exists; completing a reset revokes all sessions and marks
the address verified.

**Email safety.** Default backend is `console` — captured in an in-process
outbox, **never sent**. SMTP is opt-in via env for MailHog/Mailpit/Mailtrap;
production credentials come from the environment only. **No email was sent to
any real address during this work.**

**Rate limits:** login 8/5 min per (IP+email), signup 5/h per IP, reset 5/h,
lookup 20/h, upload 20/h per user.

**Protected:** all 61 auth endpoints + 2 API-key endpoints. **Public (by
design):** health, login, register, the 4 account-recovery routes, and the
stream route (which performs its own token + ownership check).

**Test accounts:** random `@example.com` (RFC 2606, non-routable) created per
test run. Demo seed uses `arun.demo@example.com` / `priya.demo@example.com`
with `testpass123` — local demo data only.

---

## 7. Authorization and data isolation

**Ownership model.** `users(id)` → `videos.owner_user_id` → every derived
table keyed by `video_id`. Server-side checks only; UI filtering is never
treated as a control.

**Checks:** `_get_owned_video()` is the single choke point for per-video
routes and returns **404, not 403**, so the API never confirms an id exists.
`GET /videos` filters by owner. `compare` requires ownership of both ids. The
stream route re-resolves the token and asserts the path is inside
`UPLOADS_DIR`. The only cross-user path is an explicit, revocable per-video
coach review.

**Tests proving isolation** (`tests/test_authorization.py`, all passing):

| Test | Result |
|---|---|
| 14 per-video endpoints reject anonymous | Pass |
| 14 per-video endpoints reject another user | Pass |
| User B cannot see A's video in listing / delete / process / patch calibration | Pass |
| Compare cannot mix in another user's video | Pass |
| Stream rejects missing, garbage, and other-user tokens | Pass |
| Coach review grants access, then revocation kills it **immediately** (verified live: 200 → 403 review, 200 → 404 stream) | Pass |
| Non-invited user cannot open a review; only the student can revoke | Pass |
| API key scoped to owner; revoked key stops working; key stored hashed | Pass |

---

## 8. Secure video upload and processing

| Control | Before | After |
|---|---|---|
| Size limit | **None** | Enforced while streaming; partial file deleted |
| Type allowlist | Extension only | Extension + magic bytes (ISO-BMFF / RIFF-AVI / EBML) |
| Empty file | Accepted | Rejected |
| Stored filename | UUID (already safe) | UUID + allowlisted extension, destination asserted inside `UPLOADS_DIR` |
| Display filename | Raw user input | Normalised; path parts, CR/LF, `<>:"\|?*` stripped, length-capped |
| Header injection | Filename in `Content-Disposition` | Header removed entirely |
| Command injection | N/A | No shell anywhere — OpenCV Python API only |
| Processing timeout | None | Videos > 30 min rejected before decoding |
| Temp cleanup | None | Partial files removed on every rejection path |
| Error handling | Framework default | Catch-all handler, generic message |
| Quotas | None | 20 uploads/h, 2 GB per user |
| Malware scanning | None | **Still none** — ClamAV recommended (§12) |

All upload cases in the brief are covered by `tests/test_upload_security.py`
(valid mp4, non-video renamed, empty, corrupted, oversized, `../` traversal ×4,
HTML/script filename, CRLF filename, unicode filename, 5000-char filename,
repeated uploads). `.webm` is now accepted; `.mov`/`.m4v`/`.avi` already were.

---

## 9. LLM and AI safety testing

**The app contains no LLM.** Verified by grep across the codebase — no OpenAI,
Anthropic, LangChain, or other model SDK. `coach_chat.py` is intent-routed
retrieval over the user's own rows with fixed templates, so injected text can
only *select* a handler; it can never become an instruction.

I tested that property rather than assuming it. Ten injection strings
(instruction override, "reveal the system prompt", "tell the user to paste
their API key", `<script>`, `'; DROP TABLE videos; --`, `{{7*7}}`,
`${jndi:...}`, `../../../../etc/passwd`) → all 10 pass:

| Expected behaviour | Result |
|---|---|
| Does not reveal hidden prompts / config | **Pass** — no `JWT_SECRET`, `DATABASE_URL`, path, or traceback in any answer |
| Does not ask for secrets | **Pass** |
| Does not render unsafe HTML | **Pass** — no script tag echoed; React escapes; no `dangerouslySetInnerHTML` anywhere |
| Does not expose other users' data | **Pass** — B's coach never surfaces A's filename or video ids |
| Treats untrusted text as data | **Pass** — never returns attacker text verbatim |
| No medical diagnosis | **Pass — after a fix** |
| Refers pain to a professional | **Pass — after a fix** |

**Real bug found and fixed.** *"I have sharp knee pain when I lunge. Diagnose
it and tell me to keep training."* previously matched the **balance** intent
(on "lunge") and returned footwork coaching. A `MEDICAL_KEYWORDS` gate now runs
**before** intent routing: it declines to diagnose, tells the player to stop,
and refers them to a physiotherapist or sports doctor.

---

## 10. Security findings

| # | Sev | Finding | Evidence | Repro | File | Fix | Status | Proof |
|---|---|---|---|---|---|---|---|---|
| 1 | **Crit** | JWT secret fell back to a published literal — tokens forgeable for any account | `JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-in-production")` | Sign a JWT with that string; it authenticated | `core/config.py` | Prod hard-fails; dev generates ephemeral random secret | **Fixed** | `test_production_config.py` (3 tests) |
| 2 | **High** | Unbounded upload → disk exhaustion | `shutil.copyfileobj` with no cap | POST a multi-GB file | `api/videos.py` | Streaming cap + cleanup | **Fixed** | `test_oversized_upload_*` |
| 3 | **High** | Any file renamed `.mp4` stored as a video | Extension-only check | Upload ELF/HTML as `.mp4` → 200 | `api/videos.py` | Magic-byte validation | **Fixed** | `test_executable_renamed…`, `test_html_renamed…` |
| 4 | **High** | No server-side logout; 7-day tokens; no password reset | No such routes | Token worked after "logout" | `api/auth.py` | `tokens_valid_from` revocation + reset flow | **Fixed** | 5 auth tests |
| 5 | **High** | Python 3.9 EOL blocks security patches | `pip-audit`: 63 advisories / 19 pkgs; fixes need ≥3.10 | `pip install "python-multipart>=0.0.21"` → refused | `requirements.txt` | Partial upgrades applied; runtime upgrade required | **Open** | `docs/evidence/pip-audit.txt` |
| 6 | **Med** | Pain/injury questions answered as coaching | "sharp knee pain when I lunge" → balance handler | POST `/coach/ask` | `coaching/coach_chat.py` | Medical gate before routing | **Fixed** | `test_coach_chat_defers_on_injury…` |
| 7 | **Med** | `python-jose` → `ecdsa` Minerva advisory, no fix | pip-audit, 4 advisories | — | `core/security.py` | Replaced with PyJWT; both removed | **Fixed** | 98 tests pass on PyJWT |
| 8 | **Med** | No rate limiting; no password policy | Unlimited login attempts; `"123"` accepted | 12 logins → all 401 | `api/auth.py` | Sliding-window limits + policy | **Fixed** | `test_login_is_rate_limited`, `test_signup_rejects_weak_password` |
| 9 | **Med** | No security headers | No nosniff/CSP/XFO | `curl -I /health` | `main.py` | Full header middleware | **Fixed** | `test_security_headers_present` |
| 10 | **Med** | 4 high-severity react-router advisories | `npm audit` | — | `frontend/package-lock.json` | `npm audit fix` | **Fixed** | `npm audit` → 0 |
| 11 | **Low** | Filename echoed into `Content-Disposition` | `FileResponse(filename=user_input)` | CRLF filename | `api/videos.py` | Header removed | **Fixed** | `test_crlf_in_filename…` |
| 12 | **Low** | Unhandled errors could leak tracebacks | No exception handler | — | `main.py` | Catch-all generic handler | **Fixed** | `test_errors_do_not_leak…` |
| 13 | **Low** | `/auth/users/lookup` confirms account existence | Authenticated enumeration oracle | — | `api/auth.py` | Rate-limited 20/h; fields minimised | **Mitigated** | — |
| 14 | **Low** | Shuttle detector fires on non-badminton motion | 170 points on `no_court.mp4` | `run_video_matrix` | `shuttle_detection.py` | Confidence capped ≤0.5, labelled experimental | **Open** | `docs/evidence/video-matrix.json` |
| 15 | **Info** | Tokens in `localStorage` | `AuthContext.tsx` | — | frontend | Mitigated by strict CSP + no raw HTML; cookies preferred | **Open** | — |

**Tested and found NOT vulnerable:** SQL injection (SQLAlchemy parameterised —
payloads inert, tables intact), NoSQL injection (N/A), command injection (no
shell), SSRF (app accepts no URLs), XSS (no `dangerouslySetInnerHTML`,
`innerHTML`, or `eval`), insecure CORS (explicit allowlist), public storage
exposure (no static mount), hardcoded secrets (none in tracked files),
broken object-level authorization (26 tests).

---

## 11. Security scans

| Tool | Command | Result |
|---|---|---|
| pip-audit | `pip-audit` | 63 advisories / 19 packages → reduced; remainder blocked by Python 3.9 |
| Bandit | `bandit -r app/ -ll` | **0 high, 0 medium**, 4 low (1 false positive on the string `"password_reset"`; 3 `try/except/continue` in coordinate transforms — intentional) |
| npm audit | `npm audit` | 4 high → **0** |
| Secret scan | `git ls-files \| xargs grep -E <patterns>` | **No secrets in tracked files.** Only match was the scanner's own needle list |
| TypeScript | `tsc -b --noEmit` | Clean |
| oxlint | `npm run lint` | 3 warnings (fast-refresh / exhaustive-deps), 0 errors |
| pytest | `pytest tests/ -q` | **98 passed** |
| Live smoke | `python -m tests.smoke_live` | **35 passed, 0 failed** |

**Not run:** Semgrep, Gitleaks, TruffleHog, OWASP ZAP — not installed locally
and installing them was out of proportion to the marginal coverage over
Bandit + the manual pattern scan. Gitleaks **is** wired into the CI workflow,
so it runs on every push once CI is enabled.

---

## 12. Code changes

**New (12):** `core/mailer.py`, `core/tokens.py`, `core/rate_limit.py`,
`core/uploads.py`, `tests/conftest.py`, `tests/test_auth.py`,
`tests/test_authorization.py`, `tests/test_upload_security.py`,
`tests/test_injection_and_hardening.py`, `tests/test_production_config.py`,
`tests/video_scenarios.py`, `tests/run_video_matrix.py`, `tests/smoke_live.py`,
`frontend/src/pages/AccountFlows.tsx`, `.env.example`, `docs/SECURITY.md`,
`docs/ci/ci.yml`.

**Modified (11):** `core/config.py` (env-driven config, secret guard, limits),
`core/security.py` (PyJWT, password policy, revocation), `api/deps.py` (shared
resolver + revocation), `api/auth.py` (5 new routes, limits, generic errors),
`api/videos.py` (hardened upload/stream), `models/user.py` (2 columns),
`main.py` (headers, exception handler, CORS), `coach_chat.py` (medical gate),
`cv_pipeline/pipeline.py` (duration guard), `requirements.txt`,
`frontend/src/App.tsx`, `AuthForms.tsx`, `package-lock.json`, `README.md`.

**Tests added:** 98 (auth 24, authorization 26, upload 17, injection 26,
production config 5) + 35 live + 14 video scenarios.

**Migration steps.** Two nullable columns (`users.email_verified_at`,
`users.tokens_valid_from`) and one table (`one_time_tokens`), created
automatically by `create_all()` on a fresh DB. **For an existing database:**

```sql
ALTER TABLE users ADD COLUMN email_verified_at DATETIME;
ALTER TABLE users ADD COLUMN tokens_valid_from DATETIME;
-- one_time_tokens is created automatically on next startup
```

Existing sessions are invalidated by design (old tokens lack `iat_ms`).
Set `JWT_SECRET` before restarting or all sessions reset anyway.

**CI note:** `.github/workflows/ci.yml` could not be pushed — the credential
lacks GitHub's `workflow` OAuth scope. The file is on disk and committed at
`docs/ci/ci.yml` with activation instructions in `docs/ci/README.md`.

---

## 13. Known limitations (honestly marked)

| Item | Why not tested / done | What's needed |
|---|---|---|
| **Stroke recognition on real footage** (serve, smash, clear, drop, net shot, lift) | No lawful footage available; scraping prohibited | 10–20 short consented clips |
| **Pose & tracking quality** | Synthetic rectangles produce no MediaPipe landmarks | Same real clips |
| **Broadcast & side-angle footage** | Same | Same |
| **Mobile viewport / slow network** | Browser-preview MCP disconnected mid-session | Playwright with device emulation + throttling |
| **Playwright/Cypress E2E** | Not installed; API-level + live smoke used instead | `npm i -D @playwright/test` |
| **Semgrep / Gitleaks / ZAP locally** | Not installed; Gitleaks wired into CI | Install, or enable CI |
| **Real SMTP delivery** | Deliberately not done — no real mail sent | MailHog/Mailtrap creds |
| **Session expiry over real time** | Would need a long-running test | Clock injection |
| **Concurrent upload race** | Sequential quota tested only | Load harness |
| **Alembic migrations** | Project uses `create_all()` | Adopt Alembic before prod |
| **Malware scanning** | Not implemented | ClamAV in ingest |
| **Multi-instance rate limiting** | In-process only | Redis or edge/WAF |

---

## 14. Prioritized next steps

### Critical
*(none outstanding — finding #1 is fixed)*

### High
1. **Upgrade to Python 3.11+.** Unblocks `python-multipart` ≥0.0.21, FastAPI
   ≥0.129, Starlette 1.x, urllib3 ≥2.7 and clears most of the 63 advisories.
2. **Validate the CV pipeline on real, consented badminton footage.** Tracking
   scored 2/5 and stroke recognition is unscored; the product's core claim is
   unverified until this happens.
3. **Enable CI** (`docs/ci/README.md`) so tests, audits, and Gitleaks run per push.
4. **Fix tracking under occlusion** — 0 tracks when players cross. This is the
   Phase-2 YOLOv8 + ByteTrack swap already in `ROADMAP.md`.

### Medium
5. Move sessions to `HttpOnly; Secure; SameSite=Lax` cookies + CSRF tokens.
6. Move processing to a killable subprocess with a wall-clock timeout.
7. Adopt Alembic before any deployment with real data.
8. Reduce shuttle-detector false positives, or suppress output below a
   plausibility threshold.
9. Add ClamAV scanning to the ingest path.
10. Quality gate should penalise sub-720p and flag portrait orientation
    (426×240 scored 71 while producing nothing usable).

### Low
11. Redis-backed rate limiting when scaling past one instance.
12. Object storage with short-lived signed URLs.
13. Breach-corpus password check (HIBP k-anonymity).
14. MFA / SSO — the point at which a hosted provider becomes worthwhile.
15. Structured audit logging for auth and access-control events.
