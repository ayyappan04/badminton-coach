import os
import secrets
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# APP_ENV drives the safety posture: "development" (default) allows
# conveniences like an auto-generated JWT secret and a console mailer;
# "production" refuses to start unless real secrets are supplied.
APP_ENV = os.environ.get("APP_ENV", "development").lower()
IS_PRODUCTION = APP_ENV == "production"

STORAGE_DIR = Path(os.environ.get("STORAGE_DIR", BASE_DIR / "storage"))
UPLOADS_DIR = STORAGE_DIR / "uploads"
DERIVED_DIR = STORAGE_DIR / "derived"


def ensure_local_dirs() -> None:
    """Create the local storage tree.

    Called lazily by the local storage backend and the legacy upload path --
    deliberately NOT at import time. Creating directories as an import side
    effect means merely importing this module can raise PermissionError, which
    is exactly what happens when a container mounts a root-owned volume and
    runs as a non-root user. A process configured for object storage does not
    need these directories at all and must not crash looking for them.
    """
    for directory in (UPLOADS_DIR, DERIVED_DIR):
        directory.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'app.db'}")

# --- JWT -------------------------------------------------------------------
# A hardcoded fallback secret is a critical vulnerability: anyone who reads the
# source can mint tokens for any account. In production we hard-fail; in
# development we generate an ephemeral random secret (sessions reset on
# restart, which is the correct trade for not shipping a known key).
_INSECURE_DEFAULT = "dev-secret-change-in-production"
_env_secret = os.environ.get("JWT_SECRET")

# JWT_SECRET signs and verifies THIS application's own tokens. Under
# AUTH_MODE=supabase there are none: Supabase issues the tokens and they are
# verified against its published JWKS, so the secret is never used. Demanding
# it there would fail a deployment over a value that has no effect -- which is
# a guard protecting nothing, and it stopped the first production deploy dead.
#
# It genuinely IS required for `legacy` and for `dual`, because both accept
# tokens this application signed.
_LEGACY_TOKENS_IN_USE = os.environ.get("AUTH_MODE", "legacy").lower() in ("legacy", "dual")

if _env_secret and _env_secret != _INSECURE_DEFAULT:
    JWT_SECRET = _env_secret
elif IS_PRODUCTION and _LEGACY_TOKENS_IN_USE:
    sys.exit(
        "FATAL: JWT_SECRET is unset or still the development default. "
        "Set a strong random JWT_SECRET (e.g. `openssl rand -hex 32`) before "
        "starting with APP_ENV=production and AUTH_MODE="
        f"{os.environ.get('AUTH_MODE', 'legacy')}."
    )
elif IS_PRODUCTION:
    # Supabase-only production. Generate an unusable-by-anyone value so the
    # module still has the attribute, and say plainly that it is inert.
    JWT_SECRET = secrets.token_hex(32)
    print(
        "[config] AUTH_MODE=supabase: no JWT_SECRET was supplied and none is "
        "needed. Supabase issues tokens and they are verified against its "
        "JWKS; this process signs nothing.",
        file=sys.stderr,
    )
else:
    JWT_SECRET = secrets.token_hex(32)
    print(
        "[config] APP_ENV=development: generated an ephemeral JWT secret. "
        "Sessions will not survive a restart. Set JWT_SECRET to persist them.",
        file=sys.stderr,
    )

JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", 60 * 12))  # 12h default

# --- Email -----------------------------------------------------------------
# "console" captures mail in an in-process outbox and logs it (safe default,
# never sends). "smtp" requires host/port and is only used when explicitly
# configured — see .env.example and docs/SECURITY.md.
MAIL_BACKEND = os.environ.get("MAIL_BACKEND", "console").lower()
MAIL_FROM = os.environ.get("MAIL_FROM", "no-reply@badminton-coach.local")
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 1025))
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "false").lower() == "true"

APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:5173")

EMAIL_VERIFICATION_TTL_MINUTES = int(os.environ.get("EMAIL_VERIFICATION_TTL_MINUTES", 60 * 24))
PASSWORD_RESET_TTL_MINUTES = int(os.environ.get("PASSWORD_RESET_TTL_MINUTES", 30))

# Whether an unverified account may log in. Off by default in production.
REQUIRE_EMAIL_VERIFICATION = os.environ.get(
    "REQUIRE_EMAIL_VERIFICATION", "true" if IS_PRODUCTION else "false"
).lower() == "true"

# --- CORS ------------------------------------------------------------------
CORS_ORIGINS = [
    o.strip() for o in os.environ.get(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",") if o.strip()
]

# --- Uploads ---------------------------------------------------------------
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_UPLOAD_MB", 200)) * 1024 * 1024
MAX_UPLOADS_PER_HOUR = int(os.environ.get("MAX_UPLOADS_PER_HOUR", 20))
MAX_STORAGE_BYTES_PER_USER = int(os.environ.get("MAX_STORAGE_MB_PER_USER", 2048)) * 1024 * 1024
MAX_ORIGINAL_FILENAME_LEN = 120

# --- Rate limits (requests per window, seconds) ----------------------------
RATE_LIMIT_ENABLED = os.environ.get("BC_DISABLE_RATE_LIMIT", "0") != "1"
LOGIN_RATE_LIMIT = (8, 300)          # 8 attempts / 5 min / (ip+email)
REGISTER_RATE_LIMIT = (5, 3600)      # 5 signups / hour / ip
PASSWORD_RESET_RATE_LIMIT = (5, 3600)  # 5 reset requests / hour / (ip+email)

# --- Analysis pipeline tunables --------------------------------------------
FRAME_SAMPLE_FPS = 10          # fps used for detection stages (court/player/tactics)
POSE_SAMPLE_FPS = 15           # fps used for pose + shuttle (motion-sensitive stages)
MAX_VIDEO_DURATION_S = 60 * 30
MIN_RESOLUTION_FOR_SHUTTLE = (640, 360)
PROCESSING_TIMEOUT_S = int(os.environ.get("PROCESSING_TIMEOUT_S", 900))

# The detection stages hold their sampled frames in memory at full
# resolution. Without a budget, memory scales with duration x resolution:
# a 8.4-minute 1080p match at 10 fps needs ~31 GB and OOM-kills the worker.
# When a video would exceed this budget the effective sample rate is
# reduced and the result is flagged `sparse_sampling_long_video`.
MAX_ANALYSIS_FRAME_BYTES = int(os.environ.get("MAX_ANALYSIS_FRAME_MB", 1200)) * 1024 * 1024
MIN_ANALYSIS_FPS = 0.5   # hard floor; the byte budget wins above this

# Per-frame pose landmarks are the single largest thing this system writes:
# 33 landmarks x ~15 fps x 2 players x 40 minutes is ~72,000 rows and ~130 MB
# of JSON for ONE match. They are never queried by content -- every consumer
# reads the whole sequence to rebuild one object -- so they belong in the
# gzipped analysis artifact, where the same data is ~76x smaller.
#
# When False, `pose_frames` keeps only the small queryable columns and the
# landmarks live in object storage. Persistence is skipped ONLY if the artifact
# was published successfully, so the data always exists somewhere.
PERSIST_POSE_LANDMARKS = os.environ.get("PERSIST_POSE_LANDMARKS", "false").lower() == "true"

# The in-process PipelineResult cache is a memory leak without a bound: each
# entry is tens of megabytes and a long-lived API process would accumulate one
# per video it has ever served.
PIPELINE_CACHE_MAX_ENTRIES = int(os.environ.get("PIPELINE_CACHE_MAX_ENTRIES", 8))


# ===========================================================================
# PRODUCTION ARCHITECTURE (Vercel + Supabase)
# ===========================================================================
# The three switches below decide whether this process behaves as the local
# MVP or as one tier of the production topology. They default to the local
# behaviour so `pytest` and `uvicorn` keep working with no environment set.

# local    — bytes on the worker's filesystem (dev, tests)
# supabase — private Supabase Storage buckets (production)
STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "local").lower()

# local — in-process ThreadPoolExecutor (dev, tests)
# pgmq  — Supabase Queues; survives crashes, restarts and redeploys
JOB_BACKEND = os.environ.get("JOB_BACKEND", "local").lower()

# legacy   — this app's own HS256 tokens (dev, tests, pre-migration)
# supabase — Supabase Auth tokens only
# dual     — accept both, for the cutover window
AUTH_MODE = os.environ.get("AUTH_MODE", "legacy").lower()

# --- Supabase credentials --------------------------------------------------
# SUPABASE_SERVICE_ROLE_KEY is a privileged secret: it bypasses RLS entirely.
# It may exist only in the API container and the worker container. It must
# never be exposed to the browser, and never as a VITE_* variable.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
# Legacy symmetric JWT secret. Preferred verification is asymmetric via JWKS
# (SUPABASE_URL/auth/v1/.well-known/jwks.json); this is the HS256 fallback.
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")
SUPABASE_JWT_AUD = os.environ.get("SUPABASE_JWT_AUD", "authenticated")

BUCKET_ORIGINALS = os.environ.get("SUPABASE_BUCKET_ORIGINALS", "video-originals")
BUCKET_DERIVED = os.environ.get("SUPABASE_BUCKET_DERIVED", "video-derived")
BUCKET_AVATARS = os.environ.get("SUPABASE_BUCKET_AVATARS", "avatars")

# How long a signed playback URL stays valid. Short by design: the frontend
# refreshes it rather than holding a long-lived credential.
SIGNED_URL_TTL_S = int(os.environ.get("SIGNED_URL_TTL_S", 3600))

QUEUE_ANALYSIS = os.environ.get("QUEUE_ANALYSIS", "shuttlesense_analysis")

# --- Media limits ----------------------------------------------------------
# These exist for system safety, not to be stingy. A 4K 40-minute match is a
# legitimate recording; a 200-hour 16K stream is an attempt to occupy a worker.
MAX_VIDEO_BYTES = int(os.environ.get("MAX_VIDEO_GB", 5)) * 1024 * 1024 * 1024
MAX_VIDEO_DURATION_S_HARD = int(os.environ.get("MAX_VIDEO_DURATION_S", 60 * 90))
MAX_VIDEO_WIDTH = int(os.environ.get("MAX_VIDEO_WIDTH", 7680))
MAX_VIDEO_HEIGHT = int(os.environ.get("MAX_VIDEO_HEIGHT", 4320))
MAX_VIDEO_FPS = float(os.environ.get("MAX_VIDEO_FPS", 240))

# --- Media normalization profiles ------------------------------------------
# Two profiles, because one file is not simultaneously ideal for computer
# vision and for a phone on cellular data.
#
# ANALYSIS: conservative on purpose. Badminton footage is exactly the content
# that compression destroys — a shuttle is a handful of pixels travelling at
# 300+ km/h, and limbs motion-blur. We cap resolution at 1080p rather than the
# usual 720p, keep the frame rate up to 60, and use a near-transparent CRF.
# Downstream scores would silently degrade if this were tuned for file size.
MAX_ANALYSIS_WIDTH = int(os.environ.get("MAX_ANALYSIS_WIDTH", 1920))
MAX_ANALYSIS_HEIGHT = int(os.environ.get("MAX_ANALYSIS_HEIGHT", 1080))
MAX_ANALYSIS_FPS_OUT = float(os.environ.get("MAX_ANALYSIS_FPS_OUT", 60))
ANALYSIS_CRF = int(os.environ.get("ANALYSIS_CRF", 18))
ANALYSIS_CODEC = os.environ.get("ANALYSIS_CODEC", "libx264")
ANALYSIS_PRESET = os.environ.get("ANALYSIS_PRESET", "medium")

# PLAYBACK: optimised for browser seeking and egress cost.
PLAYBACK_MAX_WIDTH = int(os.environ.get("PLAYBACK_MAX_WIDTH", 1280))
PLAYBACK_MAX_HEIGHT = int(os.environ.get("PLAYBACK_MAX_HEIGHT", 720))
PLAYBACK_CRF = int(os.environ.get("PLAYBACK_CRF", 26))
# Slow-motion phone footage is genuinely useful for coaching review, but a
# 120 fps playback proxy doubles egress for detail no browser scrubber
# resolves. 60 keeps half-speed review honest and bounds the bill.
PLAYBACK_MAX_FPS = float(os.environ.get("PLAYBACK_MAX_FPS", 60))
PLAYBACK_CODEC = os.environ.get("PLAYBACK_CODEC", "libx264")
PLAYBACK_PRESET = os.environ.get("PLAYBACK_PRESET", "veryfast")
PLAYBACK_AUDIO = os.environ.get("PLAYBACK_AUDIO", "aac")  # or "none" to strip

# Skip re-encoding when the source is already within the analysis envelope and
# in a container the pipeline reads reliably. Saves a full transcode per upload.
ALLOW_ANALYSIS_PASSTHROUGH = os.environ.get("ALLOW_ANALYSIS_PASSTHROUGH", "true").lower() == "true"

# --- FFmpeg ----------------------------------------------------------------
# Resolved lazily by app.media.ffmpeg so a missing binary is a clear error at
# use time rather than an import-time crash for processes that never transcode.
FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "")
FFPROBE_BIN = os.environ.get("FFPROBE_BIN", "")
FFMPEG_TIMEOUT_S = int(os.environ.get("FFMPEG_TIMEOUT_S", 3600))
FFPROBE_TIMEOUT_S = int(os.environ.get("FFPROBE_TIMEOUT_S", 120))

# --- Worker / queue --------------------------------------------------------
# CV work is CPU and memory bound. Scale by adding worker containers, not by
# raising this — two concurrent pipelines on one box fight for the same cores
# and the same frame-buffer budget.
WORKER_CONCURRENCY = int(os.environ.get("WORKER_CONCURRENCY", 1))
WORKER_ID = os.environ.get("WORKER_ID", "")  # defaults to hostname:pid
JOB_LEASE_S = int(os.environ.get("JOB_LEASE_S", 900))
JOB_HEARTBEAT_S = int(os.environ.get("JOB_HEARTBEAT_S", 30))
JOB_MAX_ATTEMPTS = int(os.environ.get("JOB_MAX_ATTEMPTS", 3))
QUEUE_POLL_INTERVAL_S = float(os.environ.get("QUEUE_POLL_INTERVAL_S", 5))

# LocalJobDispatcher only. True runs work inline on submit, which is what makes
# `uvicorn` alone a working dev environment. Tests that drive the claim/lease
# machinery themselves set it False so the runner, not a background thread,
# decides when a job executes.
JOB_EAGER_LOCAL = os.environ.get("JOB_EAGER_LOCAL", "true").lower() == "true"

# --- Retention / quotas ----------------------------------------------------
# Originals are never deleted as part of processing. They survive until an
# explicit lifecycle job runs, and only once derived assets are verified.
ORIGINAL_RETENTION_DAYS = int(os.environ.get("ORIGINAL_RETENTION_DAYS", 90))
RETAIN_ORIGINAL_ALWAYS = os.environ.get("RETAIN_ORIGINAL_ALWAYS", "true").lower() == "true"
MAX_ACTIVE_UPLOADS_PER_USER = int(os.environ.get("MAX_ACTIVE_UPLOADS_PER_USER", 3))
MAX_ANALYSIS_JOBS_PER_DAY = int(os.environ.get("MAX_ANALYSIS_JOBS_PER_DAY", 25))
UPLOAD_SESSION_TTL_S = int(os.environ.get("UPLOAD_SESSION_TTL_S", 24 * 3600))

# --- Observability ---------------------------------------------------------
LOG_FORMAT = os.environ.get("LOG_FORMAT", "text" if not IS_PRODUCTION else "json")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
