"""Direct-to-storage upload control plane.

Every endpoint here is small and fast by design. The API allocates a path,
records intent, and later verifies what landed. It never reads the video.

  POST   /videos/uploads                      authorize a resumable upload
  PUT    /videos/uploads/{id}/bytes           local-backend byte sink (dev only)
  POST   /videos/uploads/{id}/progress        record progress for refresh recovery
  POST   /videos/uploads/{id}/complete        verify the object, queue analysis
  POST   /videos/uploads/{id}/cancel          abandon
  GET    /videos/uploads/active               resume after a browser restart
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core import config
from app.core.observability import log
from app.core.rate_limit import check as rate_limit_check
from app.db.session import get_db
from app.models.assets import UploadSession
from app.models.user import User
from app.models.video import Video
from app.services import upload_service, usage_service, video_state as vs
from app.services.usage_service import QuotaExceeded

logger = logging.getLogger("app.api.uploads")

router = APIRouter(prefix="/videos/uploads", tags=["uploads"])


class InitiateUploadRequest(BaseModel):
    filename: str = Field(..., max_length=400)
    content_type: str = Field("", max_length=200)
    size_bytes: int = Field(..., ge=1)
    match_format: str = "unknown"
    opponent_name: Optional[str] = Field(None, max_length=200)
    recorded_at: Optional[str] = Field(None, max_length=40)


class InitiateUploadResponse(BaseModel):
    video_id: str
    bucket: str
    object_path: str
    upload_method: str
    endpoint: str
    expires_at: Optional[datetime] = None
    max_bytes: int
    headers: dict = {}
    # The browser authenticates its own upload with its Supabase session, so
    # nothing here is a credential — these are coordinates, not access.
    storage_backend: str


class UploadStatusOut(BaseModel):
    video_id: str
    status: str
    upload_method: str
    bucket: str
    object_path: str
    expected_size_bytes: int
    received_size_bytes: int
    expires_at: Optional[datetime] = None
    original_filename: str
    match_format: str
    opponent_name: Optional[str] = None


@router.post("", response_model=InitiateUploadResponse)
def initiate_upload(payload: InitiateUploadRequest, request: Request,
                    current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    rate_limit_check(f"upload:{current_user.id}", (config.MAX_UPLOADS_PER_HOUR, 3600))
    try:
        video, session, auth = upload_service.initiate(
            db, user_id=current_user.id, filename=payload.filename,
            content_type=payload.content_type, size_bytes=payload.size_bytes,
            match_format=payload.match_format, opponent_name=payload.opponent_name,
            recorded_at=payload.recorded_at,
        )
    except QuotaExceeded as exc:
        raise HTTPException(status_code=exc.status_code,
                            detail=exc.message) from exc
    except upload_service.UploadError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return InitiateUploadResponse(
        video_id=video.id, bucket=auth.bucket, object_path=auth.object_path,
        upload_method=auth.upload_method, endpoint=auth.endpoint,
        expires_at=auth.expires_at, max_bytes=auth.max_bytes,
        headers=auth.headers, storage_backend=config.STORAGE_BACKEND,
    )


@router.put("/{video_id}/bytes")
async def upload_bytes(video_id: str, request: Request,
                       current_user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """Byte sink for the LOCAL storage backend only.

    Production never routes video through this process — with
    STORAGE_BACKEND=supabase the browser TUS-uploads straight to the bucket and
    this endpoint refuses. It exists so `npm run dev` and the test suite work
    without a cloud account, and it still streams to disk with a hard cap
    rather than buffering the body.
    """
    if config.STORAGE_BACKEND != "local":
        raise HTTPException(
            status_code=409,
            detail="This deployment uploads directly to object storage. "
                   "Use the resumable endpoint returned by POST /videos/uploads.",
        )

    video = _owned_video(db, video_id, current_user)
    if video.status not in (vs.CREATED, vs.UPLOADING):
        raise HTTPException(status_code=409, detail=f"Upload is not in progress (status: {video.status}).")

    from pathlib import Path
    from app.storage import get_storage
    storage = get_storage()
    dest = storage._path(video.storage_bucket, video.storage_key)  # noqa: SLF001 — local backend only
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Resumable-ish: a client may re-PUT with a Content-Range offset. Anything
    # else truncates and starts over.
    offset = 0
    content_range = request.headers.get("content-range", "")
    if content_range.startswith("bytes "):
        try:
            offset = int(content_range.split(" ", 1)[1].split("-", 1)[0])
        except (ValueError, IndexError):
            offset = 0

    mode = "r+b" if offset and dest.exists() else "wb"
    written = offset
    try:
        with dest.open(mode) as fh:
            if offset:
                fh.seek(offset)
            async for chunk in request.stream():
                written += len(chunk)
                if written > config.MAX_VIDEO_BYTES:
                    raise HTTPException(status_code=413, detail="Upload exceeds the maximum size.")
                fh.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        log(logger, logging.WARNING, "local byte sink failed", video_id=video_id,
            detail=str(exc)[:200])
        raise HTTPException(status_code=500, detail="Upload failed. Please try again.") from exc

    upload_service.mark_uploading(db, video, received_bytes=written)
    return {"received_bytes": written, "object_path": video.storage_key}


class ProgressIn(BaseModel):
    received_bytes: int = Field(0, ge=0)


@router.post("/{video_id}/progress")
def report_progress(video_id: str, payload: ProgressIn,
                    current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Server-side record of upload progress.

    Not required for correctness — the bucket knows the truth — but it means a
    user who closes the tab and comes back on another device sees where the
    upload got to, instead of an empty screen.
    """
    video = _owned_video(db, video_id, current_user)
    upload_service.mark_uploading(db, video, received_bytes=payload.received_bytes)
    return {"ok": True}


@router.post("/{video_id}/complete")
def complete_upload(video_id: str, current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Verify the object landed intact and queue processing. Idempotent."""
    video = _owned_video(db, video_id, current_user)
    try:
        run = upload_service.complete(db, video)
    except upload_service.UploadError as exc:
        upload_service.fail(db, video, exc.code, exc.message)
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    return {
        "video_id": video.id, "status": video.status,
        "analysis_run_id": run.id, "pipeline_version": run.pipeline_version,
    }


@router.post("/{video_id}/cancel")
def cancel_upload(video_id: str, current_user: User = Depends(get_current_user),
                  db: Session = Depends(get_db)):
    video = _owned_video(db, video_id, current_user)
    if video.status in (vs.ANALYZED, vs.PROCESSING):
        raise HTTPException(status_code=409,
                            detail="This match is already being analyzed. Delete it instead.")
    upload_service.cancel(db, video)
    return {"cancelled": True}


@router.get("/active", response_model=List[UploadStatusOut])
def active_uploads(current_user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """Uploads this user left in flight. The browser calls this on load, so a
    refresh mid-upload resumes rather than losing the recording."""
    upload_service.expire_stale_sessions(db)
    sessions = (
        db.query(UploadSession)
        .filter(UploadSession.user_id == current_user.id,
                UploadSession.status.in_((vs.CREATED, vs.UPLOADING)))
        .order_by(UploadSession.created_at.desc())
        .limit(10).all()
    )
    out: List[UploadStatusOut] = []
    for session in sessions:
        video = db.get(Video, session.video_id)
        if video is None or video.deleted_at is not None:
            continue
        out.append(UploadStatusOut(
            video_id=video.id, status=video.status, upload_method=session.upload_method,
            bucket=session.storage_bucket, object_path=session.storage_path,
            expected_size_bytes=session.expected_size_bytes,
            received_size_bytes=session.received_size_bytes,
            expires_at=session.expires_at, original_filename=video.original_filename,
            match_format=video.match_format, opponent_name=video.opponent_name,
        ))
    return out


@router.get("/quota")
def quota(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    snapshot = usage_service.snapshot(db, current_user.id)
    snapshot["max_video_bytes"] = config.MAX_VIDEO_BYTES
    snapshot["max_active_uploads"] = config.MAX_ACTIVE_UPLOADS_PER_USER
    return snapshot


def _owned_video(db: Session, video_id: str, user: User) -> Video:
    video = db.get(Video, video_id)
    if not video or video.owner_user_id != user.id or video.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Video not found")
    return video
