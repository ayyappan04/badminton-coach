# Next steps

Prioritised by **risk × evidence**: items backed by a measured failure in this
repo come before items that are merely good practice. Every entry says what
the problem is, what "done" looks like, and roughly what it costs.

Effort key: **S** ≈ hours · **M** ≈ 1–3 days · **L** ≈ 1–2 weeks · **XL** ≈ a month+

---

## Critical

*Nothing outstanding.* The one critical finding from the security review — the
hardcoded JWT fallback secret, which made every token forgeable — is fixed and
covered by three tests in `backend/tests/test_production_config.py`.

---

## High

### H1 · Upgrade the runtime to Python 3.11+ — **M**

**Problem.** Python 3.9 reached end of life in October 2025. `pip-audit`
reports advisories whose fixed versions (`python-multipart` ≥0.0.21, FastAPI
≥0.129, Starlette 1.x, urllib3 ≥2.7) *all* require Python ≥3.10, so they
cannot currently be applied. This is documented in `docs/SECURITY.md §6`.

**Done when.** CI runs on 3.11 and 3.12, `pip-audit` is clean or has an
explicit reviewed allowlist, and the pins in `requirements.txt` lose their
"capped by Python 3.9" comments.

**Watch for.** MediaPipe 0.10.14 wheel availability on 3.11/3.12 — verify
before committing to the bump. If MediaPipe blocks it, that decides the pose
backend question in H3.

---

### H2 · Fix player tracking through occlusion — **L**

**Problem — measured.** The classical HOG detector produces **zero tracks**
when players cross (`occlusion` scenario), on partially visible courts, and
below ~480p. Since every downstream stage — pose, shots, biomechanics,
tactics, coaching — is keyed to tracks, this failure silently empties the
entire analysis. It is the single largest accuracy defect in the product.

**Fix.** Replace HOG + IOU with a modern detector plus a real tracker:
YOLOv8-m or RT-DETR for detection, ByteTrack or BoT-SORT for association with
re-identification across occlusion. `app/services/cv_pipeline/player_tracking.py`
already exposes the right seam — `track_players()` returns `List[Track]`, so
the swap is contained.

**Done when.** The occlusion scenario yields ≥2 persistent tracks, doubles
footage yields 4, and `track_persistence` in the real-footage matrix exceeds
0.8. Add a regression test asserting a track-count floor per scenario.

**Cost note.** Adds PyTorch (~2 GB) and effectively requires a GPU for
reasonable throughput. Budget for that before starting.

---

### H3 · Validate and then train stroke recognition — **XL**

**Problem.** Shot classification is a hand-written heuristic over wrist speed
and contact height. It is unvalidated against ground truth and produced almost
no shots across the synthetic matrix. The product's headline claim — technique
coaching — rests on it.

**Sequence.**
1. **Validate first (M).** Use the real-footage harness and the BWF manual
   protocol to measure current accuracy against human-labelled strokes. You
   cannot improve what you have not measured, and the answer may be worse than
   the heuristic's confidence values imply.
2. **Build a labelled set (L).** 10–30k labelled strokes across levels and
   camera angles, sourced through the consent/licensing pipeline already
   specified in `PRIVACY_AND_CONSENT.md`. This is the real bottleneck.
3. **Train (L).** A temporal model (TCN or small transformer) over pose +
   shuttle windows.

**Done when.** Per-class precision/recall published per stroke type, and the
UI's confidence values are calibrated against measured accuracy rather than
hand-tuned.

---

### H4 · Reduce shuttle-detector false positives — **M**

**Problem — measured.** The motion-blob heuristic emitted **170 "shuttle
points" on non-badminton footage** (a grey circle on black) and 213 under
occlusion. Confidence is capped at 0.5 and the UI labels it experimental, but
the false-positive rate is worse than that framing implies.

**Interim fix (S).** Add plausibility gating before emitting: require
trajectory consistency with projectile motion, suppress output entirely when
court calibration confidence is low, and surface a "shuttle not tracked" state
rather than a noisy trail.

**Real fix (XL).** A TrackNet-style heatmap detector trained on annotated
badminton frames — the highest-value dataset to build after H3's.

---

### H5 · Enable CI — **S**

**Problem.** `docs/ci/ci.yml` is written and complete but not active: the push
credential lacks GitHub's `workflow` scope, so it could not be committed to
`.github/workflows/`.

**Done when.** Grant the scope (or add the file via the GitHub UI) and confirm
tests, pip-audit, bandit, npm audit, build, and gitleaks all run per push.
Instructions: `docs/ci/README.md`.

---

## Medium

### M1 · Move sessions to HttpOnly cookies — **M**
Tokens currently live in `localStorage`, readable by any successful XSS.
Mitigated today by a strict CSP and no raw HTML rendering anywhere, but
`HttpOnly; Secure; SameSite=Lax` cookies plus CSRF tokens are strictly better.
Touches `AuthContext.tsx`, `api/client.ts`, and the stream endpoint's
query-parameter token.

### M2 · Killable processing subprocess — **M**
Analysis runs in a thread pool; Python threads cannot be pre-empted, so a
decode that hangs on a malformed-but-short file occupies a worker
indefinitely. Videos over 30 minutes are already rejected before decoding,
which bounds the obvious abuse. Move processing to a subprocess (or Celery)
with a hard `PROCESSING_TIMEOUT_S` kill.

### M3 · Adopt Alembic — **S**
The app calls `Base.metadata.create_all()` at startup. Fine for a fresh
database; unsafe once real user data exists. The review added two columns and
a table that currently need manual SQL on an existing DB (documented in the
report's migration section).

### M4 · Quality gate should penalise unusable footage harder — **S**
Measured gap: 426×240 footage scored **71/100** while producing zero tracks,
zero poses, and zero shuttle points. Portrait orientation scored 84 and was
not flagged at all. Weight resolution more heavily, add an aspect-ratio check,
and cap the score when downstream stages are known to be unavailable.

### M5 · Malware scanning on upload — **S**
Files are never executed and are only opened by OpenCV, but ClamAV in the
ingest path is standard practice before accepting untrusted public uploads.

### M6 · Object storage with signed URLs — **M**
Storage is a local directory today. There are no public URLs and every read is
authenticated, but production should use private buckets with short-lived
signed URLs.

### M7 · Coach content review by a qualified coach — **S**
The 24 technique references and drill library were written from widely taught
fundamentals. They read plausibly, but no qualified badminton coach has
reviewed them. Do this before any commercial use.

---

## Low

| # | Item | Effort |
|---|---|---|
| L1 | Redis-backed rate limiting (current limiter is per-process) | S |
| L2 | Breach-corpus password check (HIBP k-anonymity) | S |
| L3 | Structured audit logging for auth and access-control events | S |
| L4 | MFA / SSO — the point at which a hosted auth provider earns its keep | M |
| L5 | Racket detection (position, angle, head speed) — today's "racket path" is a wrist estimate | L |
| L6 | 3D pose lifting for real joint angles and centre of mass | XL |
| L7 | Rally outcome detection (winner / forced / unforced) — needs shuttle landing + score OCR | XL |
| L8 | Playwright E2E incl. mobile viewport and network throttling (untested today) | M |
| L9 | Frontend code-splitting (bundle >500 kB) | S |
| L10 | Add a LICENSE file | S |

---

## Suggested order

```
H1 (runtime)  ──►  H5 (CI)  ──►  H2 (tracking)  ──►  H3 step 1 (validate)
     │                              │
     └──► M3 (Alembic)              └──► H4 interim (shuttle gating)
                                         │
                        M1, M2, M4 ◄─────┘   then H3 steps 2–3 (data + train)
```

**Why this order.** H1 unblocks dependency hygiene and may constrain H2's model
choice, so it goes first. H5 is hours of work and makes every later change
safer. H2 is the largest measured accuracy defect and gates everything
downstream. H3's *validation* step is cheap and tells you whether the
expensive training work is even the right investment — do not skip straight to
collecting data.

---

## Explicitly not planned

- **Downloading BWF or other rights-reserved footage.** Covered
  observationally via `docs/BWF_MANUAL_TEST_PROTOCOL.md`. If a licence covering
  analysis use is obtained, the existing harness accepts the files unchanged.
- **Claiming rally outcomes** before shuttle-landing detection exists.
- **An LLM in the coaching path** without first re-running the injection and
  medical-safety tests against the model-backed implementation.
