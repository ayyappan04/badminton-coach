import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core import config
from app.db.session import Base, engine
import app.models  # noqa: F401 register all models on Base.metadata
from app.core import tokens as _tokens  # noqa: F401 registers one_time_tokens table
from app.api import (
    auth, videos, uploads, profile, technique, community, consent, coach,
    coach_reviews, integration,
)
from app.core.observability import configure_logging, correlate, new_request_id, metrics
from app.seed_content import seed as seed_content

logger = logging.getLogger("app")

configure_logging()

# Schema creation at import time is a development convenience only. In
# production Alembic owns the domain schema and Supabase migrations own RLS,
# storage policies and queues -- see docs/PRODUCTION_ARCHITECTURE.md. Starting
# a production process must never mutate the schema as a side effect.
if not config.IS_PRODUCTION:
    Base.metadata.create_all(engine)


def _seed_reference_content() -> None:
    """Populate the drill/technique catalogue, tolerating an absent database.

    Deliberately NOT allowed to kill the process. Seeding connects to Postgres
    at import time, so any database misconfiguration used to crash the app
    before it could serve a single request — including /api/v1/ready, the
    endpoint whose entire purpose is explaining that exact class of failure.
    Diagnostics that are unavailable precisely when they are needed are not
    diagnostics.

    The service now starts, /health returns 200 (the process IS alive), and
    /ready returns 503 naming the cause.
    """
    try:
        seed_content()
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "could not seed reference content: %s. The service will start, but "
            "/api/v1/ready will report the dependency that is failing.",
            f"{type(exc).__name__}: {exc}"[:300],
        )


_seed_reference_content()

app = FastAPI(
    title="AI Badminton Coach API",
    version="0.2.0",
    # Interactive docs expose the full API surface; keep them off in production.
    docs_url=None if config.IS_PRODUCTION else "/docs",
    redoc_url=None if config.IS_PRODUCTION else "/redoc",
    openapi_url=None if config.IS_PRODUCTION else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,   # explicit allowlist, never "*"
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    max_age=600,
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Attach a request id and echo it back.

    An incident starts with one of these and has to be traceable across the API
    container and the worker container, which never talk to each other
    directly. Honouring an inbound X-Request-Id keeps the chain intact when a
    proxy or the frontend already assigned one.
    """
    request_id = request.headers.get("x-request-id") or new_request_id()
    with correlate(request_id=request_id):
        response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Baseline response hardening.

    This is a JSON API plus a separately served SPA, so the CSP here is
    deliberately strict — the API itself never needs to load scripts, styles,
    or frames.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
    )
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cache-Control", "no-store")
    if config.IS_PRODUCTION:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    """Never leak a traceback, file path, or SQL fragment to a client.

    The detail is logged server-side with the full stack; the client gets a
    stable, generic message.
    """
    logger.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "An unexpected error occurred. Please try again."},
    )


# uploads must precede videos: both live under /videos, and FastAPI resolves
# in registration order.
app.include_router(auth.router, prefix="/api/v1")
app.include_router(uploads.router, prefix="/api/v1")
app.include_router(videos.router, prefix="/api/v1")
app.include_router(profile.router, prefix="/api/v1")
app.include_router(technique.router, prefix="/api/v1")
app.include_router(community.router, prefix="/api/v1")
app.include_router(consent.router, prefix="/api/v1")
app.include_router(coach.router, prefix="/api/v1")
app.include_router(coach_reviews.router, prefix="/api/v1")
app.include_router(integration.router, prefix="/api/v1")


@app.get("/api/v1/health")
def health():
    """Liveness. Deliberately dependency-free: a database blip must not make an
    orchestrator kill a process that is running fine."""
    return {"status": "ok", "version": app.version}


@app.get("/api/v1/ready")
def ready():
    """Readiness. Checks the dependencies this process actually needs to serve
    traffic, cheaply -- one round trip each, and never a CV operation."""
    from sqlalchemy import text
    from app.jobs import get_dispatcher
    from app.storage import get_storage

    checks = {}
    reasons = {}

    # A readiness probe must not make an outage worse. Supabase's pooler trips
    # a circuit breaker after repeated authentication failures, and polling
    # /ready during an incident was feeding it -- every check retried the
    # connection and added to the count. Failures are cached briefly so
    # repeated polls report the known state instead of re-attacking the
    # dependency. Successes are never cached.
    cached = _cached_failure()
    if cached is not None:
        checks.update(cached["checks"])
        reasons.update(cached["reasons"])
        reasons["_note"] = f"cached for {_FAILURE_CACHE_S}s to avoid hammering a failing dependency"
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "checks": checks, "reasons": reasons,
                     "storage_backend": config.STORAGE_BACKEND,
                     "job_backend": config.JOB_BACKEND,
                     "auth_mode": config.AUTH_MODE},
        )

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("readiness: database unreachable", exc_info=True)
        checks["database"] = False
        reasons["database"] = _database_hint(exc)

    try:
        storage = get_storage()
        checks["storage"] = bool(storage.health())
        if not checks["storage"]:
            detail = getattr(storage, "last_health_error", None)
            if detail:
                reasons["storage"] = detail
    except Exception as exc:  # noqa: BLE001
        checks["storage"] = False
        reasons["storage"] = f"{type(exc).__name__}: {exc}"[:200]

    try:
        checks["queue"] = bool(get_dispatcher().health())
        if not checks["queue"]:
            reasons["queue"] = "queue unreachable; check DATABASE_URL and that pgmq exists"
    except Exception as exc:  # noqa: BLE001
        checks["queue"] = False
        reasons["queue"] = f"{type(exc).__name__}: {exc}"[:200]

    # Configuration that is missing rather than broken. A blueprint prompts for
    # several values and it is easy to leave one blank; the resulting failure
    # appears somewhere unrelated and much later.
    misconfigured = []
    from app.db.session import DATABASE_URL_PLACEHOLDER
    if DATABASE_URL_PLACEHOLDER:
        misconfigured.append(
            f"DATABASE_URL still contains the placeholder "
            f"'{DATABASE_URL_PLACEHOLDER}' instead of the real password"
        )
    if config.STORAGE_BACKEND == "supabase":
        if not config.SUPABASE_URL:
            misconfigured.append("SUPABASE_URL is empty but STORAGE_BACKEND=supabase")
        if not config.SUPABASE_SERVICE_ROLE_KEY:
            misconfigured.append("SUPABASE_SERVICE_ROLE_KEY is empty but STORAGE_BACKEND=supabase")
    if config.AUTH_MODE in ("supabase", "dual") and not config.SUPABASE_URL:
        misconfigured.append(f"SUPABASE_URL is empty but AUTH_MODE={config.AUTH_MODE}")
    if config.IS_PRODUCTION and not config.CORS_ORIGINS:
        misconfigured.append("CORS_ORIGINS is empty; browser requests will be refused")
    if misconfigured:
        reasons["configuration"] = "; ".join(misconfigured)

    ok = all(checks.values()) and not misconfigured
    if not ok:
        _remember_failure(checks, reasons)
    return JSONResponse(
        status_code=200 if ok else 503,
        content={
            "status": "ready" if ok else "degraded",
            "checks": checks,
            # Only present when something is wrong. Never contains a
            # credential -- these are status codes and provider messages.
            **({"reasons": reasons} if reasons else {}),
            "storage_backend": config.STORAGE_BACKEND,
            "job_backend": config.JOB_BACKEND,
            "auth_mode": config.AUTH_MODE,
        },
    )


# Readiness failures are cached for this long. Short enough to notice a fix
# quickly, long enough that polling cannot sustain load on a broken dependency.
_FAILURE_CACHE_S = 20
_failure_cache: dict = {}


def _cached_failure():
    import time
    entry = _failure_cache.get("last")
    if entry and (time.monotonic() - entry["at"]) < _FAILURE_CACHE_S:
        return entry
    return None


def _remember_failure(checks: dict, reasons: dict) -> None:
    import time
    _failure_cache["last"] = {"at": time.monotonic(), "checks": dict(checks),
                              "reasons": dict(reasons)}


def _database_hint(exc: Exception) -> str:
    """Turn a connection failure into something actionable.

    "Network is unreachable" against an IPv6 literal is the single most common
    Supabase deployment failure: the DIRECT connection (db.<ref>.supabase.co)
    resolves to IPv6 only, and most managed hosts — Render's free tier
    included — have no IPv6 egress. The fix is a pooler hostname, and nothing
    in the raw error says so.
    """
    text = str(exc)
    lowered = text.lower()

    if "network is unreachable" in lowered or "no route to host" in lowered:
        return (
            "cannot reach the database host. Supabase's DIRECT connection "
            "(db.<ref>.supabase.co) is IPv6-only and most hosts have no IPv6 "
            "egress. Use a POOLER connection string instead: "
            "aws-0-<region>.pooler.supabase.com — port 6543 for this API, "
            "port 5432 (session mode) for the worker."
        )
    if "ecircuitbreaker" in lowered or "temporarily blocked" in lowered:
        return (
            "Supabase's pooler has temporarily blocked new connections after "
            "repeated authentication failures. The credentials you have NOW may "
            "be correct — this is a cooldown from earlier attempts. Fix "
            "DATABASE_URL if it is still wrong, then wait a few minutes; it "
            "clears on its own."
        )
    if "password authentication failed" in lowered:
        # Against a pooler this usually is NOT the password. The pooler is
        # multi-tenant and identifies the project from the username, so a bare
        # `postgres` fails here while being correct for a direct connection.
        if 'user "postgres"' in text:
            return (
                "the pooler rejected the username. Supabase's pooler needs "
                "postgres.<project_ref>, not a bare postgres — the project is "
                "identified by the username, not the host. Check DATABASE_URL, "
                "or set SUPABASE_URL so it can be derived automatically."
            )
        return "the database password in DATABASE_URL is wrong."
    if "does not exist" in lowered and "database" in lowered:
        return "that database name does not exist; check the end of DATABASE_URL."
    if "timeout" in lowered or "timed out" in lowered:
        return "the database did not answer in time; check the host and any IP allow-list."
    if "psycopg2" in lowered:
        return (
            "DATABASE_URL asked for the psycopg2 driver, which is not installed. "
            "Use postgresql:// or postgresql+psycopg:// — both are accepted."
        )
    return f"cannot connect; check DATABASE_URL ({type(exc).__name__})"


@app.get("/api/v1/metrics")
def metrics_endpoint(request: Request):
    """Instrumentation snapshot.

    Not public: in production it requires the operations token, because queue
    depths and failure counts are operational intelligence.
    """
    import os
    token = os.environ.get("METRICS_TOKEN", "")
    if config.IS_PRODUCTION:
        if not token or request.headers.get("x-metrics-token") != token:
            raise HTTPException(status_code=404, detail="Not found")
    return metrics.snapshot()
