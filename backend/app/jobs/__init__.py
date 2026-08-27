"""Dispatcher selection."""
from __future__ import annotations

from functools import lru_cache

from app.core import config
from app.jobs.base import (  # noqa: F401  re-exported
    JobDispatcher, JobMessage, OP_ANALYZE, OP_CLEANUP, OP_INGEST, ALL_OPERATIONS,
)


@lru_cache(maxsize=1)
def get_dispatcher() -> "JobDispatcher":
    if config.JOB_BACKEND == "pgmq":
        from app.jobs.pgmq import PgmqJobDispatcher
        return PgmqJobDispatcher()
    from app.jobs.local import LocalJobDispatcher
    return LocalJobDispatcher()


def reset_dispatcher_cache() -> None:
    get_dispatcher.cache_clear()
