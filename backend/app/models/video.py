from typing import Optional
from sqlalchemy import String, Float, Integer, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase


class Video(TimestampedBase):
    __tablename__ = "videos"

    owner_user_id: Mapped[str] = mapped_column(String, index=True)
    storage_path: Mapped[str] = mapped_column(String)
    original_filename: Mapped[str] = mapped_column(String)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    resolution_w: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    resolution_h: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    match_format: Mapped[str] = mapped_column(String, default="unknown")  # singles/doubles/unknown
    opponent_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    recorded_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="uploaded")
    progress_pct: Mapped[int] = mapped_column(Integer, default=0)
    stage: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    camera_view_hint: Mapped[str] = mapped_column(String, default="unknown")
    processing_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_summary: Mapped[Optional[str]] = mapped_column(String, nullable=True)  # e.g. "Win 21-18"
    quality_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 0-100 from the V2 quality gate
    quality_report: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    pipeline_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class Calibration(TimestampedBase):
    __tablename__ = "calibration"

    video_id: Mapped[str] = mapped_column(String, index=True)
    method: Mapped[str] = mapped_column(String, default="auto_hough")
    homography_matrix: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    court_corners_px: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class TrackedPerson(TimestampedBase):
    __tablename__ = "tracked_persons"

    video_id: Mapped[str] = mapped_column(String, index=True)
    track_id: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String, default="unassigned")  # self/partner/opponent1/opponent2/unassigned
    bounding_boxes: Mapped[list] = mapped_column(JSON, default=list)
    first_frame: Mapped[int] = mapped_column(Integer, default=0)
    last_frame: Mapped[int] = mapped_column(Integer, default=0)
    track_confidence: Mapped[float] = mapped_column(Float, default=0.0)
