from typing import Optional
from datetime import datetime
from sqlalchemy import String, Float, Integer, JSON, Text, BigInteger, DateTime, Index, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase
from app.models.types import JSONType


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
    quality_report: Mapped[Optional[dict]] = mapped_column(JSONType, nullable=True)
    pipeline_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # --- object storage ----------------------------------------------------
    # `storage_path` above is the legacy local absolute path and stays for
    # rows created before the migration. Production rows carry the bucket and
    # key of the ORIGINAL asset; every other file lives in `video_assets`.
    storage_bucket: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    storage_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # --- authoritative source metadata (from ffprobe, not from the browser) --
    source_size_bytes: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    source_container: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_video_codec: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_audio_codec: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_rotation: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_bitrate: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    checksum_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    # --- analysis state ----------------------------------------------------
    analysis_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_analysis_run_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # `processing_error` above stays the safe, user-facing sentence. These add
    # the machine-readable half the UI needs to decide whether to offer Retry.
    processing_error_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    processing_error_retryable: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_stage: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # --- lifecycle ---------------------------------------------------------
    # Soft delete: access stops immediately, object cleanup runs asynchronously.
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    original_retained_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_videos_owner_created", "owner_user_id", "created_at"),
        Index("ix_videos_owner_status", "owner_user_id", "status"),
        Index("ix_videos_status_updated", "status", "updated_at"),
        Index("ix_videos_owner_checksum", "owner_user_id", "checksum_sha256"),
    )


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
