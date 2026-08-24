"""In-process sliding-window rate limiting.

Scope and honesty: this is a single-process, in-memory limiter. It is a real
control for a single-instance deployment (which is what this app currently
targets) and it meaningfully slows credential stuffing and reset-flooding.
It is NOT sufficient behind multiple workers or replicas — those need a shared
store (Redis) or an edge/WAF limit. That limitation is recorded in
docs/SECURITY.md rather than papered over.
"""
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from fastapi import HTTPException, Request, status

from app.core import config

_buckets: Dict[str, Deque[float]] = defaultdict(deque)
_lock = threading.Lock()


def reset_all() -> None:
    """Clear every bucket (used between tests)."""
    with _lock:
        _buckets.clear()


def client_ip(request: Request) -> str:
    """Best-effort client identity.

    X-Forwarded-For is only trusted when TRUST_PROXY_HEADERS is enabled,
    because a client can otherwise spoof it to dodge limits.
    """
    import os
    if os.environ.get("TRUST_PROXY_HEADERS", "false").lower() == "true":
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check(key: str, limit_spec: Tuple[int, int]) -> None:
    """Raise 429 if `key` has exceeded `(max_events, window_seconds)`."""
    if not config.RATE_LIMIT_ENABLED:
        return
    max_events, window = limit_spec
    now = time.monotonic()
    cutoff = now - window

    with _lock:
        bucket = _buckets[key]
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= max_events:
            retry_after = int(bucket[0] + window - now) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many attempts. Please wait and try again.",
                headers={"Retry-After": str(retry_after)},
            )
        bucket.append(now)
