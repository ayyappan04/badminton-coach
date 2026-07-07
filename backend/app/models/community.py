from typing import Optional
from datetime import datetime

from sqlalchemy import String, Float, DateTime, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase


class Friendship(TimestampedBase):
    __tablename__ = "friendships"

    user_id_a: Mapped[str] = mapped_column(String, index=True)
    user_id_b: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending/accepted/blocked


class SharedClip(TimestampedBase):
    __tablename__ = "shared_clips"

    video_id: Mapped[str] = mapped_column(String, index=True)
    created_by_user_id: Mapped[str] = mapped_column(String, index=True)
    clip_start_s: Mapped[float] = mapped_column(Float)
    clip_end_s: Mapped[float] = mapped_column(Float)
    visibility: Mapped[str] = mapped_column(String, default="private")
    caption: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class PracticePlan(TimestampedBase):
    __tablename__ = "practice_plans"

    created_by_user_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String, default="practice")  # practice/match
    participants: Mapped[list] = mapped_column(JSON, default=list)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime)
    location: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    linked_drill_ids: Mapped[list] = mapped_column(JSON, default=list)


class Club(TimestampedBase):
    __tablename__ = "clubs"

    name: Mapped[str] = mapped_column(String)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owner_user_id: Mapped[str] = mapped_column(String, index=True)


class ClubMembership(TimestampedBase):
    __tablename__ = "club_memberships"

    club_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    role: Mapped[str] = mapped_column(String, default="member")  # member/coach/admin


class Challenge(TimestampedBase):
    __tablename__ = "challenges"

    created_by_user_id: Mapped[str] = mapped_column(String, index=True)
    opponent_user_id: Mapped[str] = mapped_column(String, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")
    result: Mapped[Optional[str]] = mapped_column(String, nullable=True)
