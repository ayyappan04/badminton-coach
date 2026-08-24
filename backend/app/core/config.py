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

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
DERIVED_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'app.db'}")

# --- JWT -------------------------------------------------------------------
# A hardcoded fallback secret is a critical vulnerability: anyone who reads the
# source can mint tokens for any account. In production we hard-fail; in
# development we generate an ephemeral random secret (sessions reset on
# restart, which is the correct trade for not shipping a known key).
_INSECURE_DEFAULT = "dev-secret-change-in-production"
_env_secret = os.environ.get("JWT_SECRET")

if _env_secret and _env_secret != _INSECURE_DEFAULT:
    JWT_SECRET = _env_secret
elif IS_PRODUCTION:
    sys.exit(
        "FATAL: JWT_SECRET is unset or still the development default. "
        "Set a strong random JWT_SECRET (e.g. `openssl rand -hex 32`) before "
        "starting with APP_ENV=production."
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
