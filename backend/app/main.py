import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core import config
from app.db.session import Base, engine
import app.models  # noqa: F401 register all models on Base.metadata
from app.core import tokens as _tokens  # noqa: F401 registers one_time_tokens table
from app.api import (
    auth, videos, profile, technique, community, consent, coach, coach_reviews, integration,
)
from app.seed_content import seed as seed_content

logger = logging.getLogger("app")

Base.metadata.create_all(engine)
seed_content()

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


app.include_router(auth.router, prefix="/api/v1")
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
    return {"status": "ok"}
