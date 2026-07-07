from typing import Optional
from sqlalchemy import String, Boolean, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase


class UserCorrection(TimestampedBase):
    """A manual fix the user made to pipeline output (court corners, player
    identity). Serves three purposes: audit trail, immediate re-application,
    and — only with the user's training-contribution consent — a future
    supervised-training signal."""

    __tablename__ = "user_corrections"

    user_id: Mapped[str] = mapped_column(String, index=True)
    video_id: Mapped[str] = mapped_column(String, index=True)
    correction_type: Mapped[str] = mapped_column(String)  # court_corners | player_identity
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    applied: Mapped[bool] = mapped_column(Boolean, default=False)


class ProcessingJob(TimestampedBase):
    """Per-stage processing record: retry handling + audit trail for the
    event-driven pipeline (V2)."""

    __tablename__ = "processing_jobs"

    video_id: Mapped[str] = mapped_column(String, index=True)
    stage: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending/running/succeeded/failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
