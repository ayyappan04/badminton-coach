"""Structured logging and metrics, correlation-first.

The rule that shapes this file: a production incident starts with one video ID
and has to end with the full story of what happened to it, across an API
container and a worker container that never spoke directly. So every log line
carries the identifiers needed to reassemble that story, and none of them
carry a token, a key or a signed URL.
"""
from __future__ import annotations

import contextvars
import json
import logging
import os
import socket
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Optional

from app.core import config

# Correlation identifiers, propagated implicitly so call sites don't have to
# thread them through every function signature.
_request_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("request_id", default=None)
_video_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("video_id", default=None)
_run_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("analysis_run_id", default=None)
_job_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("job_id", default=None)
_user_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("user_id", default=None)

#: Never serialise these, whatever the key is nested in.
_REDACT_KEYS = frozenset({
    "authorization", "token", "access_token", "refresh_token", "password",
    "hashed_password", "apikey", "api_key", "service_role_key", "jwt_secret",
    "signed_url", "signedurl", "secret", "cookie", "set-cookie",
})


def worker_identity() -> str:
    return config.WORKER_ID or f"{socket.gethostname()}:{os.getpid()}"


def new_request_id() -> str:
    return uuid.uuid4().hex[:16]


def redact(value: Any) -> Any:
    """Defence in depth for log payloads: even if a caller passes a whole
    settings dict, the credentials do not reach the log sink."""
    if isinstance(value, dict):
        return {
            k: ("[redacted]" if k.lower() in _REDACT_KEYS else redact(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value


@contextmanager
def correlate(*, request_id: Optional[str] = None, video_id: Optional[str] = None,
              analysis_run_id: Optional[str] = None, job_id: Optional[str] = None,
              user_id: Optional[str] = None):
    tokens = []
    for var, val in (
        (_request_id, request_id), (_video_id, video_id), (_run_id, analysis_run_id),
        (_job_id, job_id), (_user_id, user_id),
    ):
        if val is not None:
            tokens.append((var, var.set(val)))
    try:
        yield
    finally:
        for var, tok in reversed(tokens):
            var.reset(tok)


def current_context() -> Dict[str, str]:
    ctx = {
        "request_id": _request_id.get(), "video_id": _video_id.get(),
        "analysis_run_id": _run_id.get(), "job_id": _job_id.get(),
        "user_id": _user_id.get(),
    }
    return {k: v for k, v in ctx.items() if v}


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in current_context().items():
            setattr(record, key, value)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
                  + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "worker_id": worker_identity(),
        }
        payload.update(current_context())
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload.update(redact(extra))
        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exc"] = self.formatException(record.exc_info)[-4000:]
        return json.dumps(payload, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ctx = current_context()
        suffix = " ".join(f"{k}={v}" for k, v in ctx.items())
        base = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<7} {record.name}: {record.getMessage()}"
        if suffix:
            base = f"{base}  [{suffix}]"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


_configured = False


def configure_logging(force: bool = False) -> None:
    global _configured
    if _configured and not force:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if config.LOG_FORMAT == "json" else TextFormatter())
    handler.addFilter(ContextFilter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))
    # httpx logs a line per request at INFO, including the full URL — which for
    # storage signing calls is an object path. Quiet by default.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    _configured = True


def log(logger: logging.Logger, level: int, message: str, **fields: Any) -> None:
    logger.log(level, message, extra={"extra_fields": fields})


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
# An in-process registry, exposed at /api/v1/metrics. Deliberately not a
# Prometheus dependency: the point is that the code is instrumented, so
# swapping the sink later is a one-file change rather than an archaeology
# project across forty call sites.

class _Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[str, float] = {}
        self._gauges: Dict[str, float] = {}
        self._timers: Dict[str, list] = {}

    @staticmethod
    def _key(name: str, labels: Optional[Dict[str, str]]) -> str:
        if not labels:
            return name
        parts = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{parts}}}"

    def incr(self, name: str, value: float = 1, **labels: str) -> None:
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + value

    def gauge(self, name: str, value: float, **labels: str) -> None:
        with self._lock:
            self._gauges[self._key(name, labels)] = value

    def observe(self, name: str, seconds: float, **labels: str) -> None:
        key = self._key(name, labels)
        with self._lock:
            bucket = self._timers.setdefault(key, [])
            bucket.append(seconds)
            # Bounded: a long-lived worker must not grow a list forever.
            if len(bucket) > 1000:
                del bucket[: len(bucket) - 1000]

    @contextmanager
    def timed(self, name: str, **labels: str):
        started = time.monotonic()
        try:
            yield
        finally:
            self.observe(name, time.monotonic() - started, **labels)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            timers = {}
            for key, values in self._timers.items():
                if not values:
                    continue
                ordered = sorted(values)
                timers[key] = {
                    "count": len(ordered),
                    "p50": round(ordered[len(ordered) // 2], 4),
                    "p95": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 4),
                    "max": round(ordered[-1], 4),
                }
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "timers": timers,
            }


metrics = _Metrics()

# Named here so the set is discoverable and spelling stays consistent.
UPLOADS_STARTED = "uploads_started"
UPLOADS_COMPLETED = "uploads_completed"
UPLOADS_FAILED = "uploads_failed"
UPLOADED_BYTES = "uploaded_bytes"
NORMALIZATION_SECONDS = "normalization_duration_seconds"
ANALYSIS_SECONDS = "analysis_duration_seconds"
QUEUE_WAIT_SECONDS = "queue_wait_seconds"
PROCESSING_FAILURES = "processing_failures_by_stage"
STORAGE_BYTES_ORIGINAL = "storage_bytes_original"
STORAGE_BYTES_DERIVED = "storage_bytes_derived"
JOBS_RETRIED = "analysis_jobs_retried"
JOBS_DEAD_LETTERED = "analysis_jobs_dead_lettered"
STALE_LEASES_RECLAIMED = "stale_leases_reclaimed"
