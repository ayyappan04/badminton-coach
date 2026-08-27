"""Upload lifecycle: authorize, verify, enqueue.

The control plane's entire job in an upload is three cheap operations —
allocate an immutable object key, record intent, and later confirm that what
landed in the bucket matches what was promised. The bytes go browser -> object
storage and are never seen by this process.

Consistency across Postgres and object storage is handled by ordering rather
than by pretending a distributed transaction exists:

  1. object exists in the bucket   (verified, not assumed)
  2. DB row becomes `uploaded`, asset row written, usage incremented
  3. analysis run created and job enqueued  -- same transaction as (2)

If step 3's process dies, step 2 has already committed, so the video shows as
uploaded-but-not-started and `requeue_stalled` picks it up. Nothing is lost;
something is merely late.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.core import config
from app.core.observability import (
    UPLOADS_COMPLETED, UPLOADS_FAILED, UPLOADS_STARTED, UPLOADED_BYTES,
    log, metrics,
)
from app.core.uploads import sanitize_display_filename, validated_extension
from app.jobs import JobMessage, OP_INGEST, get_dispatcher
from app.models.assets import ORIGINAL, UploadSession, VideoAsset
from app.models.runs import AnalysisRun, PENDING
from app.models.video import Video
from app.services import usage_service, video_state as vs
from app.storage import UploadAuthorization, get_storage
from app.storage.base import guess_content_type

logger = logging.getLogger("app.upload")

VALID_MATCH_FORMATS = {"singles", "doubles", "unknown"}


class UploadError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


def initiate(db: Session, *, user_id: str, filename: str, content_type: str,
             size_bytes: int, match_format: str = "unknown",
             opponent_name: Optional[str] = None,
             recorded_at: Optional[str] = None) -> Tuple[Video, UploadSession, UploadAuthorization]:
    """Create the video record and authorize a direct-to-storage upload."""
    if match_format not in VALID_MATCH_FORMATS:
        raise UploadError("invalid_match_format",
                          f"match_format must be one of {sorted(VALID_MATCH_FORMATS)}")

    # The extension allowlist still applies, but only to pick the stored key's
    # suffix. It is a convenience filter, not a security control -- ffprobe
    # decides what the file actually is, after it has landed.
    display_name = sanitize_display_filename(filename)
    ext = validated_extension(filename).lstrip(".")

    usage_service.check_can_start_upload(db, user_id, size_bytes)

    video = Video(
        owner_user_id=user_id,
        storage_path="",                     # legacy column; unused for new rows
        original_filename=display_name,
        match_format=match_format,
        opponent_name=(opponent_name or "").strip()[:80] or None,
        recorded_at=recorded_at,
        status=vs.CREATED,
        progress_pct=0,
        content_type=content_type or guess_content_type(ext),
        source_size_bytes=size_bytes,
    )
    db.add(video)
    db.flush()

    storage = get_storage()
    auth = storage.authorize_upload(
        user_id=user_id, video_id=video.id, ext=ext,
        content_type=video.content_type or "video/mp4", size_bytes=size_bytes,
    )
    video.storage_bucket = auth.bucket
    video.storage_key = auth.object_path

    session = UploadSession(
        video_id=video.id, user_id=user_id, status=vs.CREATED,
        upload_method=auth.upload_method,
        storage_bucket=auth.bucket, storage_path=auth.object_path,
        expected_size_bytes=size_bytes,
        declared_content_type=content_type,
        expires_at=auth.expires_at or datetime.now(timezone.utc) + timedelta(
            seconds=config.UPLOAD_SESSION_TTL_S),
    )
    db.add(session)
    db.commit()

    metrics.incr(UPLOADS_STARTED)
    log(logger, logging.INFO, "upload authorized", video_id=video.id,
        bucket=auth.bucket, method=auth.upload_method, size_bytes=size_bytes)
    return video, session, auth


def mark_uploading(db: Session, video: Video, received_bytes: int = 0) -> None:
    """Recorded so a refreshed browser can find out an upload was in flight."""
    vs.advance(video, vs.UPLOADING, strict=False)
    session = _session_for(db, video.id)
    if session:
        session.status = vs.UPLOADING
        if received_bytes:
            session.received_size_bytes = received_bytes
    db.commit()


def complete(db: Session, video: Video, *, enqueue: bool = True) -> AnalysisRun:
    """Verify the object really landed, then queue processing.

    Idempotent: calling it twice on the same video returns the existing active
    run rather than starting a second pipeline. The upload button being
    double-clicked is not an exotic scenario.
    """
    if video.status in (vs.ANALYZED, vs.PROCESSING, vs.QUEUED, vs.NORMALIZING,
                        vs.VALIDATING, vs.NEEDS_PLAYER_SELECTION):
        existing = current_or_active_run(db, video.id)
        if existing:
            return existing

    storage = get_storage()
    stat = storage.stat(video.storage_bucket, video.storage_key)
    if stat is None:
        metrics.incr(UPLOADS_FAILED, reason="object_missing")
        raise UploadError(
            "object_missing",
            "We couldn't find the uploaded file. Please try uploading again.", 409,
        )
    if stat.size_bytes <= 0:
        metrics.incr(UPLOADS_FAILED, reason="empty_object")
        raise UploadError("empty_object", "The uploaded file is empty.", 400)

    session = _session_for(db, video.id)
    expected = (session.expected_size_bytes if session else 0) or video.source_size_bytes or 0
    if expected and stat.size_bytes != expected:
        # A truncated upload usually still parses. Catching the mismatch now
        # turns a confusing CV failure twenty minutes later into an immediate,
        # accurate "that upload didn't finish".
        metrics.incr(UPLOADS_FAILED, reason="size_mismatch")
        raise UploadError(
            "size_mismatch",
            "The upload didn't finish completely. Please try uploading again.", 409,
        )

    video.source_size_bytes = stat.size_bytes
    vs.advance(video, vs.UPLOADED, strict=False)

    asset = _upsert_original_asset(db, video, stat)
    usage_service.add_asset_bytes(db, video.owner_user_id, ORIGINAL, stat.size_bytes)

    if session:
        session.status = vs.UPLOADED
        session.received_size_bytes = stat.size_bytes
        session.completed_at = datetime.now(timezone.utc)

    metrics.incr(UPLOADS_COMPLETED)
    metrics.incr(UPLOADED_BYTES, stat.size_bytes)

    run = create_run(db, video, source_asset_id=asset.id)
    vs.advance(video, vs.QUEUED, stage="queued", progress_pct=0, strict=False)

    if enqueue:
        message = JobMessage(
            operation=OP_INGEST, video_id=video.id, analysis_run_id=run.id,
            pipeline_version=run.pipeline_version,
        )
        run.idempotency_key = message.idempotency_key
        dispatcher = get_dispatcher()
        # pgmq shares this transaction, so "run created" and "job queued"
        # commit together or not at all -- which is precisely the atomicity an
        # outbox pattern would otherwise be needed to provide.
        if getattr(dispatcher, "backend", "") == "pgmq":
            dispatcher.enqueue(message, db=db)
            db.commit()
        else:
            db.commit()
            dispatcher.enqueue(message)
    else:
        db.commit()

    log(logger, logging.INFO, "upload completed and queued", video_id=video.id,
        analysis_run_id=run.id, size_bytes=stat.size_bytes)
    return run


def create_run(db: Session, video: Video, *, source_asset_id: Optional[str] = None,
               make_current: bool = False) -> AnalysisRun:
    """Reprocessing adds a run. It never edits the previous one — yesterday's
    numbers stay interpretable as yesterday's numbers."""
    from app.services.cv_pipeline.pipeline import PIPELINE_VERSION

    attempt = db.query(AnalysisRun).filter_by(video_id=video.id).count() + 1
    run = AnalysisRun(
        video_id=video.id, owner_user_id=video.owner_user_id,
        pipeline_version=PIPELINE_VERSION, status=PENDING,
        attempt=attempt, max_attempts=config.JOB_MAX_ATTEMPTS,
        source_asset_id=source_asset_id, is_current=make_current,
        configuration=_run_configuration(),
    )
    db.add(run)
    db.flush()
    video.current_analysis_run_id = video.current_analysis_run_id or run.id
    return run


def _run_configuration() -> dict:
    """Provenance: the exact knobs in force for this run, so a number can be
    traced back to the settings that produced it."""
    from app.storage.paths import MEDIA_TRANSFORM_VERSION
    return {
        "frame_sample_fps": config.FRAME_SAMPLE_FPS,
        "pose_sample_fps": config.POSE_SAMPLE_FPS,
        "max_analysis_frame_bytes": config.MAX_ANALYSIS_FRAME_BYTES,
        "min_analysis_fps": config.MIN_ANALYSIS_FPS,
        "media_transform_version": MEDIA_TRANSFORM_VERSION,
        "analysis_profile": {
            "max_width": config.MAX_ANALYSIS_WIDTH, "max_height": config.MAX_ANALYSIS_HEIGHT,
            "max_fps": config.MAX_ANALYSIS_FPS_OUT, "crf": config.ANALYSIS_CRF,
            "codec": config.ANALYSIS_CODEC,
        },
    }


def current_or_active_run(db: Session, video_id: str) -> Optional[AnalysisRun]:
    from app.models.runs import ACTIVE_RUN_STATES
    return (
        db.query(AnalysisRun)
        .filter(AnalysisRun.video_id == video_id,
                AnalysisRun.status.in_(tuple(ACTIVE_RUN_STATES)))
        .order_by(AnalysisRun.created_at.desc())
        .first()
    )


def cancel(db: Session, video: Video, reason: str = "cancelled by user") -> None:
    session = _session_for(db, video.id)
    if session:
        session.status = vs.CANCELLED
        session.error_message = reason[:500]
    for run in db.query(AnalysisRun).filter(
        AnalysisRun.video_id == video.id,
        AnalysisRun.status.in_(("pending", "claimed", "running")),
    ).all():
        run.status = "cancelled"
        run.completed_at = datetime.now(timezone.utc)
    vs.advance(video, vs.CANCELLED, strict=False)
    db.commit()
    log(logger, logging.INFO, "upload cancelled", video_id=video.id)


def fail(db: Session, video: Video, code: str, message: str, detail: str = "") -> None:
    video.processing_error = message
    video.processing_error_code = code
    video.processing_error_retryable = False
    vs.advance(video, vs.FAILED, strict=False)
    session = _session_for(db, video.id)
    if session:
        session.status = vs.FAILED
        session.error_message = message[:500]
    db.commit()
    metrics.incr(UPLOADS_FAILED, reason=code)
    log(logger, logging.WARNING, "upload failed", video_id=video.id, code=code, detail=detail[:400])


def _session_for(db: Session, video_id: str) -> Optional[UploadSession]:
    return (
        db.query(UploadSession)
        .filter_by(video_id=video_id)
        .order_by(UploadSession.created_at.desc())
        .first()
    )


def _upsert_original_asset(db: Session, video: Video, stat) -> VideoAsset:
    existing = db.query(VideoAsset).filter_by(
        video_id=video.id, asset_type=ORIGINAL, deleted_at=None).first()
    if existing:
        existing.size_bytes = stat.size_bytes
        existing.mime_type = stat.content_type or existing.mime_type
        return existing
    asset = VideoAsset(
        video_id=video.id, owner_user_id=video.owner_user_id, asset_type=ORIGINAL,
        storage_bucket=video.storage_bucket, storage_path=video.storage_key,
        mime_type=stat.content_type or video.content_type, size_bytes=stat.size_bytes,
    )
    db.add(asset)
    db.flush()
    return asset


def expire_stale_sessions(db: Session) -> int:
    """Abandoned uploads must not hold a user's concurrency slot forever."""
    now = datetime.now(timezone.utc)
    stale = db.query(UploadSession).filter(
        UploadSession.status.in_(("created", "uploading")),
        UploadSession.expires_at.isnot(None),
        UploadSession.expires_at < now,
    ).all()
    for session in stale:
        session.status = vs.CANCELLED
        session.error_message = "upload session expired"
        video = db.get(Video, session.video_id)
        if video and video.status in (vs.CREATED, vs.UPLOADING):
            vs.advance(video, vs.CANCELLED, strict=False)
    db.commit()
    return len(stale)
