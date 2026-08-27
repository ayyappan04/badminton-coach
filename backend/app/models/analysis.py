from typing import Optional
from sqlalchemy import String, Float, Integer, JSON, Text, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase
from app.models.types import JSONType


class PoseFrame(TimestampedBase):
    __tablename__ = "pose_frames"

    tracked_person_id: Mapped[str] = mapped_column(String, index=True)
    video_id: Mapped[str] = mapped_column(String, index=True)
    frame_index: Mapped[int] = mapped_column(Integer)
    timestamp_s: Mapped[float] = mapped_column(Float)
    landmarks: Mapped[list] = mapped_column(JSON, default=list)  # 33 mediapipe landmarks
    stance_label: Mapped[str] = mapped_column(String, default="unknown")
    balance_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    # `pose_samples_from_db` filters on tracked_person_id and orders by
    # frame_index; without the composite this is the single hottest sort in
    # the scorecard path.
    __table_args__ = (Index("ix_pose_frames_person_frame", "tracked_person_id", "frame_index"),)

class ShuttleFrame(TimestampedBase):
    __tablename__ = "shuttle_frames"

    video_id: Mapped[str] = mapped_column(String, index=True)
    frame_index: Mapped[int] = mapped_column(Integer)
    timestamp_s: Mapped[float] = mapped_column(Float)
    position_px: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    position_court: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    estimated_speed_mps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    __table_args__ = (Index("ix_shuttle_frames_video_frame", "video_id", "frame_index"),)

class Rally(TimestampedBase):
    __tablename__ = "rallies"

    video_id: Mapped[str] = mapped_column(String, index=True)
    rally_index: Mapped[int] = mapped_column(Integer)
    phases: Mapped[list] = mapped_column(JSONType, default=list)  # [{phase, start_s, end_s, confidence}]
    ending_shot_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    ending_track_role: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    start_frame: Mapped[int] = mapped_column(Integer)
    end_frame: Mapped[int] = mapped_column(Integer)
    start_timestamp_s: Mapped[float] = mapped_column(Float)
    end_timestamp_s: Mapped[float] = mapped_column(Float)
    shot_count: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    __table_args__ = (Index("ix_rallies_video_index", "video_id", "rally_index"),)

class Shot(TimestampedBase):
    __tablename__ = "shots"

    rally_id: Mapped[str] = mapped_column(String, index=True)
    video_id: Mapped[str] = mapped_column(String, index=True)
    tracked_person_id: Mapped[str] = mapped_column(String, index=True)
    shot_index_in_rally: Mapped[int] = mapped_column(Integer)
    frame_index: Mapped[int] = mapped_column(Integer)
    timestamp_s: Mapped[float] = mapped_column(Float)
    shot_type: Mapped[str] = mapped_column(String, default="unknown")
    side: Mapped[str] = mapped_column(String, default="unknown")
    contact_height: Mapped[str] = mapped_column(String, default="unknown")
    intent: Mapped[str] = mapped_column(String, default="unknown")
    outcome: Mapped[str] = mapped_column(String, default="unknown")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    __table_args__ = (Index("ix_shots_video_timestamp", "video_id", "timestamp_s"),)

class MatchAnalytics(TimestampedBase):
    """Pre-aggregated whole-match analytics (V2). One row per video; each
    block inside `analytics` carries its own confidence and a `basis` string
    stating what it was computed from — see docs/V2_DESIGN.md §4."""

    __tablename__ = "match_analytics"

    video_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    feature_version: Mapped[str] = mapped_column(String, default="2.0.0")
    # JSONB: the comparison endpoints reach into `blocks` by name, and the
    # GIN index in migration 0002 needs a binary column to index.
    analytics: Mapped[dict] = mapped_column(JSONType, default=dict)


class CoachingInsight(TimestampedBase):
    __tablename__ = "coaching_insights"

    video_id: Mapped[str] = mapped_column(String, index=True)
    tracked_person_id: Mapped[str] = mapped_column(String, index=True)
    related_shot_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    timestamp_s: Mapped[float] = mapped_column(Float)
    category: Mapped[str] = mapped_column(String)  # technique/footwork/positioning/tactics/stamina
    observed_action: Mapped[str] = mapped_column(Text)
    likely_impact: Mapped[str] = mapped_column(Text)
    correction: Mapped[str] = mapped_column(Text)
    drill_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    limitations: Mapped[list] = mapped_column(JSON, default=list)

    __table_args__ = (Index("ix_insights_video_timestamp", "video_id", "timestamp_s"),)
