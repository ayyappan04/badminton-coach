"""Physical files, and the upload sessions that produce them.

The MVP conflated the logical match with the single file on disk
(`videos.storage_path`). That works until a video has an original, an analysis
proxy, a playback proxy, a poster, a thumbnail and a pile of evidence clips —
each with its own lifecycle, size and retention rule. `video_assets` is the
inventory that makes storage accounting, reconciliation and staleness
detection possible at all.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, BigInteger, Float, DateTime, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase
from app.models.types import JSONType

# asset_type values
ORIGINAL = "original"
ANALYSIS_PROXY = "analysis_proxy"
PLAYBACK_PROXY = "playback_proxy"
THUMBNAIL = "thumbnail"
POSTER = "poster"
EVIDENCE_CLIP = "evidence_clip"
OVERLAY_MANIFEST = "overlay_manifest"
ANALYSIS_ARTIFACT = "analysis_artifact"

#: Assets that can be thrown away and rebuilt from the original. Everything
#: not in this set is either irreplaceable or user data.
REPRODUCIBLE = frozenset({
    ANALYSIS_PROXY, PLAYBACK_PROXY, THUMBNAIL, POSTER, EVIDENCE_CLIP,
    OVERLAY_MANIFEST, ANALYSIS_ARTIFACT,
})


class VideoAsset(TimestampedBase):
    __tablename__ = "video_assets"

    video_id: Mapped[str] = mapped_column(String, index=True)
    owner_user_id: Mapped[str] = mapped_column(String, index=True)

    asset_type: Mapped[str] = mapped_column(String, index=True)
    storage_bucket: Mapped[str] = mapped_column(String)
    storage_path: Mapped[str] = mapped_column(String)

    mime_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)

    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    fps: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    codec: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    container: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    checksum_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    # Staleness detection: a derived asset is stale when the transform that
    # produced it, or the checksum of what it was produced from, no longer
    # matches current configuration.
    transform_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_asset_id: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    source_checksum: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    extra: Mapped[Optional[dict]] = mapped_column(JSONType, nullable=True)

    # Tombstone: the row survives deletion of the object so reconciliation can
    # tell "we deleted this on purpose" from "this object went missing".
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)

    __table_args__ = (
        Index("ix_video_assets_video_type", "video_id", "asset_type"),
        Index("ix_video_assets_bucket_path", "storage_bucket", "storage_path"),
        Index("ix_video_assets_owner_live", "owner_user_id", "deleted_at"),
    )

    @property
    def is_live(self) -> bool:
        return self.deleted_at is None


class UploadSession(TimestampedBase):
    """Coordinates application state with an in-flight object upload.

    Stores no credential. The browser authenticates its TUS upload with its own
    Supabase session token; this row exists so that a refresh, a crashed tab or
    a second device can find out what was already in progress.
    """
    __tablename__ = "upload_sessions"

    video_id: Mapped[str] = mapped_column(String, index=True)
    user_id: Mapped[str] = mapped_column(String, index=True)

    status: Mapped[str] = mapped_column(String, default="created", index=True)
    upload_method: Mapped[str] = mapped_column(String, default="tus")

    storage_bucket: Mapped[str] = mapped_column(String)
    storage_path: Mapped[str] = mapped_column(String)

    expected_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    received_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    declared_content_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_upload_sessions_user_status", "user_id", "status"),
    )


class StorageUsage(TimestampedBase):
    """Authoritative per-user byte accounting.

    Replaces `sum(Path(v.storage_path).stat().st_size for ...)`, which stat'd
    every file the user owned on every single upload attempt and returned zero
    for anything not on this machine's disk.
    """
    __tablename__ = "storage_usage"

    user_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    original_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    derived_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    asset_count: Mapped[int] = mapped_column(Integer, default=0)
    last_reconciled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    @property
    def total_bytes(self) -> int:
        return (self.original_bytes or 0) + (self.derived_bytes or 0)
