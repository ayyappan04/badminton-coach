"""Analysis executions, and the event log they emit.

A video is not its analysis. Pipeline versions change, algorithms improve, and
a user may legitimately want yesterday's numbers to still mean what they meant
yesterday. Separating `analysis_runs` from `videos` is what lets reprocessing
add a run instead of silently rewriting history.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Float, DateTime, Text, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase
from app.models.types import JSONType

# run status
PENDING = "pending"
CLAIMED = "claimed"
RUNNING = "running"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"

ACTIVE_RUN_STATES = frozenset({PENDING, CLAIMED, RUNNING})


class AnalysisRun(TimestampedBase):
    __tablename__ = "analysis_runs"

    video_id: Mapped[str] = mapped_column(String, index=True)
    owner_user_id: Mapped[str] = mapped_column(String, index=True)

    pipeline_version: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default=PENDING, index=True)

    # Exactly one run per video may be `is_current`. Enforced by a partial
    # unique index in Postgres (see the Alembic migration) rather than by
    # convention, because "which numbers are the real ones" is not a question
    # that tolerates a race.
    is_current: Mapped[bool] = mapped_column(Boolean, default=False)

    attempt: Mapped[int] = mapped_column(Integer, default=1)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)

    stage: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)

    # Worker lease. A run whose heartbeat has gone stale is reclaimable; this
    # is what stops a crashed worker from parking a video in `processing`
    # forever.
    worker_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    claimed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)

    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    source_asset_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    analysis_asset_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    error_code: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)   # safe, user-facing
    error_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)    # internal, never sent to a client
    failed_stage: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, default=True)

    # Provenance: exactly which knobs produced these numbers.
    configuration: Mapped[Optional[dict]] = mapped_column(JSONType, nullable=True)
    metrics: Mapped[Optional[dict]] = mapped_column(JSONType, nullable=True)

    # Idempotency key: video + run + operation + pipeline version. A duplicate
    # queue delivery resolves to the same key and is dropped rather than
    # starting a second pipeline.
    idempotency_key: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)

    __table_args__ = (
        Index("ix_analysis_runs_video_created", "video_id", "created_at"),
        Index("ix_analysis_runs_status_lease", "status", "lease_expires_at"),
    )


class ProcessingEvent(TimestampedBase):
    """Append-only progress/audit trail.

    Intentionally coarse: one row per stage transition and per notable
    incident, never one per frame. A 40-minute match produces on the order of
    fifteen rows.
    """
    __tablename__ = "processing_events"

    video_id: Mapped[str] = mapped_column(String, index=True)
    analysis_run_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    owner_user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)

    event_type: Mapped[str] = mapped_column(String, index=True)  # stage_started|stage_completed|failed|retried|...
    stage: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    progress_pct: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    worker_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    extra: Mapped[Optional[dict]] = mapped_column(JSONType, nullable=True)

    __table_args__ = (
        Index("ix_processing_events_video_created", "video_id", "created_at"),
    )
