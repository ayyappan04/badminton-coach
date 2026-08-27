"""Per-user storage accounting.

The MVP computed usage by stat'ing every file the user owned, on every upload
attempt. That is O(videos) filesystem syscalls on a request path, and it
returns zero the moment the bytes live in a bucket rather than on this
machine's disk. Usage is now a maintained counter with a reconciliation job
behind it, which is the only shape that survives object storage.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core import config
from app.models.assets import ORIGINAL, StorageUsage, VideoAsset
from app.models.runs import AnalysisRun

logger = logging.getLogger("app.usage")


def get_or_create(db: Session, user_id: str) -> StorageUsage:
    row = db.query(StorageUsage).filter_by(user_id=user_id).first()
    if row is None:
        row = StorageUsage(user_id=user_id)
        db.add(row)
        db.flush()
    return row


def add_asset_bytes(db: Session, user_id: str, asset_type: str, delta_bytes: int) -> StorageUsage:
    row = get_or_create(db, user_id)
    if asset_type == ORIGINAL:
        row.original_bytes = max(0, (row.original_bytes or 0) + delta_bytes)
    else:
        row.derived_bytes = max(0, (row.derived_bytes or 0) + delta_bytes)
    row.asset_count = max(0, (row.asset_count or 0) + (1 if delta_bytes > 0 else -1))
    return row


def recalculate(db: Session, user_id: str) -> StorageUsage:
    """Authoritative recount from `video_assets`. Cheap enough to run on demand
    and the repair path when the counter and reality disagree."""
    row = get_or_create(db, user_id)
    assets = db.query(VideoAsset).filter_by(owner_user_id=user_id, deleted_at=None).all()
    row.original_bytes = sum(a.size_bytes or 0 for a in assets if a.asset_type == ORIGINAL)
    row.derived_bytes = sum(a.size_bytes or 0 for a in assets if a.asset_type != ORIGINAL)
    row.asset_count = len(assets)
    row.last_reconciled_at = datetime.now(timezone.utc)
    return row


def snapshot(db: Session, user_id: str) -> dict:
    row = get_or_create(db, user_id)
    limit = config.MAX_STORAGE_BYTES_PER_USER
    used = row.total_bytes
    return {
        "original_bytes": row.original_bytes or 0,
        "derived_bytes": row.derived_bytes or 0,
        "total_bytes": used,
        "limit_bytes": limit,
        "percent_used": round(100 * used / limit, 1) if limit else 0.0,
        "asset_count": row.asset_count or 0,
    }


class QuotaExceeded(Exception):
    def __init__(self, code: str, message: str, status_code: int = 429):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def check_can_start_upload(db: Session, user_id: str, declared_size: int) -> None:
    """Every limit that must hold before we hand out an upload authorization.

    Checked here rather than at completion because the alternative is letting
    someone push 5 GB into a bucket and only then telling them no.
    """
    if declared_size <= 0:
        raise QuotaExceeded("invalid_size", "The file size could not be determined.", 400)
    if declared_size > config.MAX_VIDEO_BYTES:
        gb = config.MAX_VIDEO_BYTES / (1024 ** 3)
        raise QuotaExceeded(
            "file_too_large",
            f"That file is larger than the {gb:.0f} GB limit for a single upload.", 413,
        )

    from app.models.assets import UploadSession
    active = db.query(UploadSession).filter(
        UploadSession.user_id == user_id,
        UploadSession.status.in_(("created", "uploading")),
    ).count()
    if active >= config.MAX_ACTIVE_UPLOADS_PER_USER:
        raise QuotaExceeded(
            "too_many_active_uploads",
            f"You already have {active} uploads in progress. "
            "Finish or cancel one before starting another.", 429,
        )

    usage = get_or_create(db, user_id)
    if usage.total_bytes + declared_size > config.MAX_STORAGE_BYTES_PER_USER:
        limit_gb = config.MAX_STORAGE_BYTES_PER_USER / (1024 ** 3)
        raise QuotaExceeded(
            "storage_limit_reached",
            f"This upload would exceed your {limit_gb:.1f} GB of storage. "
            "Delete an old match to free space.", 507,
        )

    since = datetime.now(timezone.utc) - timedelta(days=1)
    todays_runs = db.query(AnalysisRun).filter(
        AnalysisRun.owner_user_id == user_id, AnalysisRun.created_at >= since,
    ).count()
    if todays_runs >= config.MAX_ANALYSIS_JOBS_PER_DAY:
        raise QuotaExceeded(
            "daily_analysis_limit",
            f"You've reached the limit of {config.MAX_ANALYSIS_JOBS_PER_DAY} "
            "analyses per day. Try again tomorrow.", 429,
        )


def find_duplicate(db: Session, user_id: str, checksum: str,
                   exclude_video_id: Optional[str] = None):
    """Same bytes, same owner. Deliberately scoped to one user: cross-user
    deduplication would let someone learn that another account holds a
    specific file, which is a privacy leak dressed as an optimisation."""
    if not checksum:
        return None
    from app.models.video import Video
    q = db.query(Video).filter(
        Video.owner_user_id == user_id,
        Video.checksum_sha256 == checksum,
        Video.deleted_at.is_(None),
    )
    if exclude_video_id:
        q = q.filter(Video.id != exclude_video_id)
    return q.first()
