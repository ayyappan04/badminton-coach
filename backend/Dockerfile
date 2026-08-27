# syntax=docker/dockerfile:1.7
# =============================================================================
# ShuttleSense Python image.
#
# ONE image, two entrypoints. The API container and the worker container run
# identical code and differ only in the command they start — so a job handler
# can never be tested against one build and deployed as another, and every
# managed host can build it without a pre-existing local tag.
#
# Runtime is Python 3.12. The MVP was pinned to 3.9 (EOL October 2025), which
# capped FastAPI, Starlette and python-multipart below their patched releases.
# Moving the container runtime forward is what unblocks those upgrades; see
# docs/SECURITY.md.
# =============================================================================

# ---------- builder ----------------------------------------------------------
FROM python:3.12-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

# Build-only toolchain. It stays in this stage; the runtime image never gets a
# compiler, which removes a whole class of post-exploitation convenience.
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements.txt ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt

# ---------- runtime ----------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    APP_ENV=production \
    LOG_FORMAT=json

# ffmpeg is a hard runtime dependency of the media pipeline, not an optional
# extra: probe, normalize and thumbnail all shell out to it.
# libGL/libglib are what OpenCV links against even in headless use.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg \
      libgl1 \
      libglib2.0-0 \
      curl \
      tini \
    && rm -rf /var/lib/apt/lists/* \
    && ffmpeg -version | head -1 \
    && ffprobe -version | head -1

COPY --from=builder /opt/venv /opt/venv

# Non-root. The worker downloads and decodes files uploaded by strangers and
# hands them to ffmpeg; that process should own as little as possible.
RUN groupadd --system --gid 1001 shuttle \
    && useradd --system --uid 1001 --gid shuttle --create-home shuttle

WORKDIR /app
COPY --chown=shuttle:shuttle . /app

# Scratch space for per-run working directories. Ephemeral by contract — the
# worker treats local disk as temporary and object storage as durable.
# /data exists in the IMAGE so that a named volume mounted there inherits this
# ownership. Docker seeds an empty named volume from the image's directory,
# permissions included; without this the volume arrives root-owned and a
# non-root container cannot write to it.
RUN mkdir -p /app/storage /tmp/shuttlesense /data \
    && chown -R shuttle:shuttle /app/storage /tmp/shuttlesense /data

USER shuttle

EXPOSE 8000

# tini reaps the ffmpeg children the media pipeline spawns; without a real
# init, a killed transcode leaves a zombie per job.
ENTRYPOINT ["/usr/bin/tini", "--"]

# Liveness only. Deliberately does NOT touch the database, storage or the
# queue: a dependency blip should show up in /ready and in alerting, not cause
# an orchestrator to kill a process that is working fine.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/api/v1/health || exit 1

# Default command is the API. The worker runs this same image with the command
# overridden to `python -m app.jobs.runner` — one image, so the worker's
# dependencies cannot drift from the ones the handler code was tested against.
# Every host config in deploy/ does exactly that.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
