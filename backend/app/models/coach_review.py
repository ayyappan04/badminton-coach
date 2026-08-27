from typing import Optional
from sqlalchemy import String, Float, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase


class CoachReview(TimestampedBase):
    """A student's explicit, per-video invitation for a specific coach to view
    that match's analysis and add notes (Phase 4). Access is review-scoped:
    the coach can see only the invited video, only while the review is active,
    and the student can revoke at any time. This is the only path by which a
    non-owner ever sees another player's analysis."""

    __tablename__ = "coach_reviews"

    video_id: Mapped[str] = mapped_column(String, index=True)
    student_user_id: Mapped[str] = mapped_column(String, index=True)
    coach_user_id: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="active")  # active / completed / revoked
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # optional note from the student


class CoachNote(TimestampedBase):
    """A human coach's annotation on a reviewed match — anchored to a video
    timestamp and optionally to a specific AI insight, with a stance that lets
    the coach confirm, adjust, or override what the AI said."""

    __tablename__ = "coach_notes"

    review_id: Mapped[str] = mapped_column(String, index=True)
    video_id: Mapped[str] = mapped_column(String, index=True)
    coach_user_id: Mapped[str] = mapped_column(String, index=True)
    timestamp_s: Mapped[float] = mapped_column(Float, default=0.0)
    comment: Mapped[str] = mapped_column(Text)
    related_insight_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    stance: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # agree / adjust / disagree (vs the AI insight)


# Declared outside the classes so the file's existing shape is untouched.
Index("ix_coach_reviews_coach_status", CoachReview.coach_user_id, CoachReview.status)
Index("ix_coach_reviews_video_status", CoachReview.video_id, CoachReview.status)
Index("ix_coach_notes_video_created", CoachNote.video_id, CoachNote.created_at)
