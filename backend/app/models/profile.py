from typing import Optional
from datetime import datetime

from sqlalchemy import String, Integer, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase, utcnow


class PlayerProfile(TimestampedBase):
    __tablename__ = "player_profiles"

    user_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    matches_analyzed_count: Mapped[int] = mapped_column(Integer, default=0)
    play_style_labels: Mapped[list] = mapped_column(JSON, default=list)  # [{label, evidence, confidence}]
    strengths: Mapped[list] = mapped_column(JSON, default=list)
    weaknesses: Mapped[list] = mapped_column(JSON, default=list)
    radar_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    training_plan: Mapped[dict] = mapped_column(JSON, default=dict)


class ProfileHistorySnapshot(TimestampedBase):
    __tablename__ = "profile_history_snapshots"

    user_id: Mapped[str] = mapped_column(String, index=True)
    video_id: Mapped[str] = mapped_column(String)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    radar_scores: Mapped[dict] = mapped_column(JSON, default=dict)
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
