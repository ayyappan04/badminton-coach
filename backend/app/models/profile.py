from typing import Optional
from datetime import datetime

from sqlalchemy import String, Integer, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase, utcnow
from app.models.types import JSONType


class PlayerProfile(TimestampedBase):
    __tablename__ = "player_profiles"

    user_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    matches_analyzed_count: Mapped[int] = mapped_column(Integer, default=0)
    play_style_labels: Mapped[list] = mapped_column(JSONType, default=list)  # [{label, evidence, confidence}]
    strengths: Mapped[list] = mapped_column(JSONType, default=list)
    weaknesses: Mapped[list] = mapped_column(JSONType, default=list)
    radar_scores: Mapped[dict] = mapped_column(JSONType, default=dict)
    training_plan: Mapped[dict] = mapped_column(JSONType, default=dict)


class ProfileHistorySnapshot(TimestampedBase):
    __tablename__ = "profile_history_snapshots"

    user_id: Mapped[str] = mapped_column(String, index=True)
    video_id: Mapped[str] = mapped_column(String)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    radar_scores: Mapped[dict] = mapped_column(JSONType, default=dict)
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
