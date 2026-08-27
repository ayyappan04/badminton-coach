"""Append-only processing event log.

Volume is intentional: one row per stage boundary and per incident, never one
per frame. A 40-minute match produces roughly fifteen rows, which is enough to
answer "what happened to this video" without turning the audit trail into the
largest table in the database.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.core.observability import log
from app.models.runs import ProcessingEvent

logger = logging.getLogger("app.events")

STAGE_STARTED = "stage_started"
STAGE_COMPLETED = "stage_completed"
QUEUED = "queued"
CLAIMED = "claimed"
PROGRESS = "progress"
FAILED = "failed"
RETRIED = "retried"
LEASE_RECLAIMED = "lease_reclaimed"
CANCELLED = "cancelled"
COMPLETED = "completed"
DEAD_LETTERED = "dead_lettered"


def record(db: Session, *, video_id: str, event_type: str,
           analysis_run_id: Optional[str] = None, owner_user_id: Optional[str] = None,
           stage: Optional[str] = None, progress_pct: Optional[int] = None,
           message: Optional[str] = None, duration_ms: Optional[int] = None,
           worker_id: Optional[str] = None, commit: bool = True,
           **extra) -> ProcessingEvent:
    event = ProcessingEvent(
        video_id=video_id, analysis_run_id=analysis_run_id, owner_user_id=owner_user_id,
        event_type=event_type, stage=stage, progress_pct=progress_pct,
        message=(message or "")[:2000] or None, duration_ms=duration_ms,
        worker_id=worker_id, extra=extra or None,
    )
    db.add(event)
    if commit:
        db.commit()
    log(logger, logging.INFO, f"event {event_type}", stage=stage,
        progress_pct=progress_pct, detail=message)
    return event


def history(db: Session, video_id: str, limit: int = 100) -> list[ProcessingEvent]:
    return (
        db.query(ProcessingEvent)
        .filter_by(video_id=video_id)
        .order_by(ProcessingEvent.created_at.asc())
        .limit(limit).all()
    )
