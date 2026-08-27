from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, resolve_user_from_token
from app.core import config
from app.core.config import UPLOADS_DIR
from app.core.rate_limit import check as rate_limit_check
from app.core.uploads import save_upload, ALLOWED_EXTENSIONS
from app.db.session import get_db, SessionLocal
from app.models.user import User
from app.models.video import Video, Calibration, TrackedPerson
from app.models.analysis import Rally, Shot, CoachingInsight, MatchAnalytics
from app.models.corrections import UserCorrection
from app.services import analysis_service
from app.services.cv_pipeline.overlay import build_overlay_manifest
from app.services.cv_pipeline.court_detection import solve_homography_from_corners
from app.services.coaching.technique_scores import compute_technique_scores
from app.services import deletion_service, events as events_service, upload_service, video_state as vs
from app.storage import get_storage
from app import worker

router = APIRouter(prefix="/videos", tags=["videos"])



class VideoOut(BaseModel):
    id: str
    original_filename: str
    duration_seconds: Optional[float] = None
    fps: Optional[float] = None
    resolution_w: Optional[int] = None
    resolution_h: Optional[int] = None
    match_format: str
    opponent_name: Optional[str] = None
    status: str
    progress_pct: int
    stage: Optional[str] = None
    processing_error: Optional[str] = None
    result_summary: Optional[str] = None
    # Already stored on the model; surfaced here so the match library can show
    # recording quality and date without an extra request per video.
    quality_score: Optional[int] = None
    recorded_at: Optional[str] = None

    # --- production lifecycle ---------------------------------------------
    # `status` keeps its original vocabulary and gains the states that used to
    # be invisible (created/uploading/validating/queued/normalizing). Clients
    # that only understood the old five still work; `status_group` exists so
    # they do not have to enumerate the new ones.
    status_group: Optional[str] = None
    status_label: Optional[str] = None
    processing_error_code: Optional[str] = None
    processing_error_retryable: Optional[bool] = None
    failed_stage: Optional[str] = None
    analysis_confidence: Optional[float] = None
    duration_seconds_source: Optional[float] = None
    source_size_bytes: Optional[int] = None
    has_playback_asset: bool = False
    thumbnail_url: Optional[str] = None

    class Config:
        from_attributes = True


def _video_out(db: Session, video: Video, *, with_thumbnail: bool = False) -> VideoOut:
    """Serialise a Video, including the derived facts the UI needs.

    Thumbnail signing is opt-in because it costs one storage round trip per
    video; the library asks for it, single-video reads do not.
    """
    from app.models.assets import PLAYBACK_PROXY, THUMBNAIL, VideoAsset

    out = VideoOut.model_validate(video)
    out.status_group = vs.GROUP.get(video.status)
    out.status_label = vs.LABEL.get(video.status)
    out.duration_seconds_source = video.duration_seconds
    out.has_playback_asset = db.query(VideoAsset).filter_by(
        video_id=video.id, asset_type=PLAYBACK_PROXY, deleted_at=None).first() is not None

    if with_thumbnail:
        thumb = db.query(VideoAsset).filter_by(
            video_id=video.id, asset_type=THUMBNAIL, deleted_at=None).first()
        if thumb is not None:
            try:
                out.thumbnail_url = get_storage().signed_read_url(
                    thumb.storage_bucket, thumb.storage_path, config.SIGNED_URL_TTL_S)
            except Exception:  # noqa: BLE001 — a missing thumbnail is cosmetic
                pass
    return out


VALID_MATCH_FORMATS = {"singles", "doubles", "unknown"}


@router.post("", response_model=VideoOut)
def upload_video(
    request: Request,
    file: UploadFile = File(...),
    match_format: str = Form("unknown"),
    opponent_name: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Accept a match recording.

    Hardening applied here (see app/core/uploads.py):
    streaming size cap, container magic-byte validation, server-generated
    storage filename, sanitised display filename, per-user hourly rate limit
    and total storage quota.
    """
    # LEGACY PATH. Production uploads go browser -> object storage via
    # POST /videos/uploads; routing multi-gigabyte bodies through the API
    # process is exactly what that redesign removed. This endpoint stays so
    # local development and the existing test suite keep working, and it
    # refuses to run in production.
    if config.STORAGE_BACKEND != "local" or config.IS_PRODUCTION:
        raise HTTPException(
            status_code=410,
            detail="Direct multipart upload is disabled. "
                   "Use POST /videos/uploads for resumable direct-to-storage uploads.",
        )

    rate_limit_check(f"upload:{current_user.id}", (config.MAX_UPLOADS_PER_HOUR, 3600))

    if match_format not in VALID_MATCH_FORMATS:
        raise HTTPException(status_code=400, detail=f"match_format must be one of {sorted(VALID_MATCH_FORMATS)}")

    used = sum(
        (Path(v.storage_path).stat().st_size if Path(v.storage_path).exists() else 0)
        for v in db.query(Video).filter_by(owner_user_id=current_user.id).all()
    )
    if used >= config.MAX_STORAGE_BYTES_PER_USER:
        raise HTTPException(
            status_code=507,
            detail=(
                f"You have reached your {config.MAX_STORAGE_BYTES_PER_USER // (1024*1024)} MB "
                "storage limit. Delete an old match to free space."
            ),
        )

    dest_path, display_name, size_bytes = save_upload(file)

    if used + size_bytes > config.MAX_STORAGE_BYTES_PER_USER:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(status_code=507, detail="This upload would exceed your storage limit.")

    safe_opponent = (opponent_name or "").strip()[:80] or None

    video = Video(
        owner_user_id=current_user.id, storage_path=str(dest_path),
        original_filename=display_name, match_format=match_format,
        opponent_name=safe_opponent, status="uploaded",
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    return video


@router.get("", response_model=List[VideoOut])
def list_videos(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    videos = (
        db.query(Video)
        .filter(Video.owner_user_id == current_user.id, Video.deleted_at.is_(None))
        .order_by(Video.created_at.desc()).all()
    )
    return [_video_out(db, v, with_thumbnail=True) for v in videos]


@router.get("/{video_id}", response_model=VideoOut)
def get_video(video_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    video = _get_owned_video(db, video_id, current_user)
    return _video_out(db, video, with_thumbnail=True)


@router.delete("/{video_id}")
def delete_video(video_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Tombstone now, purge objects asynchronously.

    Access ends the moment this returns: the video disappears from listings,
    every coach review on it is revoked, and queued analysis is cancelled.
    Object deletion is a separate idempotent job, because a storage API being
    briefly unavailable must not leave a user unable to delete their own
    footage.
    """
    video = _get_owned_video(db, video_id, current_user)
    deletion_service.soft_delete_video(db, video)
    return {"deleted": True, "cleanup": "queued"}


@router.get("/{video_id}/playback")
def playback_url(video_id: str, current_user: User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    """A short-lived signed URL for the PLAYBACK proxy.

    Deliberately not the original: a user rewatching a rally twelve times
    should pull a 40 MB proxy twelve times, not a 4 GB source. The original
    exists for analysis, reprocessing and high-quality evidence.

    The URL expires. The frontend re-requests rather than caching it, and the
    signature is never logged.
    """
    from app.models.assets import ANALYSIS_PROXY, ORIGINAL, PLAYBACK_PROXY, VideoAsset

    video = _get_owned_video(db, video_id, current_user, allow_coach=True)

    asset = None
    for asset_type in (PLAYBACK_PROXY, ANALYSIS_PROXY, ORIGINAL):
        asset = db.query(VideoAsset).filter_by(
            video_id=video.id, asset_type=asset_type, deleted_at=None).first()
        if asset is not None:
            break

    if asset is None:
        # Pre-migration rows still have their bytes on local disk.
        if video.storage_path and Path(video.storage_path).exists():
            return {
                "url": f"/api/v1/videos/{video.id}/stream",
                "requires_token_query": True,
                "asset_type": "legacy_local",
                "expires_in": None,
            }
        raise HTTPException(status_code=404, detail="No playable video is available yet.")

    try:
        url = get_storage().signed_read_url(
            asset.storage_bucket, asset.storage_path, config.SIGNED_URL_TTL_S)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503,
                            detail="Video playback is temporarily unavailable.") from exc

    return {
        "url": url,
        "asset_type": asset.asset_type,
        "expires_in": config.SIGNED_URL_TTL_S,
        "width": asset.width, "height": asset.height,
        "duration_seconds": asset.duration_seconds,
        "size_bytes": asset.size_bytes,
        "requires_token_query": config.STORAGE_BACKEND == "local",
    }


@router.get("/objects/{bucket}/{object_key:path}")
def read_object(bucket: str, object_key: str, token: str = Query(...)):
    """Local-backend object reads, with the same ownership rules the signed
    Supabase URL enforces.

    Only reachable with STORAGE_BACKEND=local. It exists so `<video>` works in
    development; in production the browser fetches a signed CDN URL and this
    process is not in the data path at all.
    """
    if config.STORAGE_BACKEND != "local":
        raise HTTPException(status_code=404, detail="Not found")

    db = SessionLocal()
    try:
        user = resolve_user_from_token(db, token)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

        from app.models.assets import VideoAsset
        from app.storage.paths import owner_of

        # Two independent checks: the key's owner prefix (which is what
        # Storage RLS enforces in production) and the asset row's owner.
        if owner_of(object_key) != user.id:
            asset = db.query(VideoAsset).filter_by(
                storage_bucket=bucket, storage_path=object_key, deleted_at=None).first()
            if asset is None or not _may_read_video(db, asset.video_id, user.id):
                raise HTTPException(status_code=404, detail="Not found")

        storage = get_storage()
        try:
            path = storage._path(bucket, object_key)  # noqa: SLF001 — local backend only
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="Invalid object path") from exc
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="Not found")

        media_type = "video/mp4" if path.suffix in (".mp4", ".m4v") else None
        return FileResponse(str(path), media_type=media_type or "application/octet-stream",
                            headers={"X-Content-Type-Options": "nosniff"})
    finally:
        db.close()


@router.post("/{video_id}/reprocess")
def reprocess_video(video_id: str, current_user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    """Start a NEW analysis run. The previous one is retained.

    Pipeline versions change; a user should be able to re-analyze a match
    without last month's numbers being silently rewritten underneath them.
    """
    from app.jobs import JobMessage, OP_INGEST, get_dispatcher

    video = _get_owned_video(db, video_id, current_user)
    active = upload_service.current_or_active_run(db, video.id)
    if active is not None:
        return {"status": video.status, "analysis_run_id": active.id, "started": False}
    if video.status in (vs.CREATED, vs.UPLOADING):
        raise HTTPException(status_code=409, detail="This upload hasn't finished yet.")

    run = upload_service.create_run(db, video)
    message = JobMessage(operation=OP_INGEST, video_id=video.id,
                         analysis_run_id=run.id, pipeline_version=run.pipeline_version)
    run.idempotency_key = message.idempotency_key
    video.processing_error = None
    video.processing_error_code = None
    vs.advance(video, vs.QUEUED, stage="queued", progress_pct=0, strict=False)

    dispatcher = get_dispatcher()
    if getattr(dispatcher, "backend", "") == "pgmq":
        dispatcher.enqueue(message, db=db)
        db.commit()
    else:
        db.commit()
        dispatcher.enqueue(message)

    return {"status": video.status, "analysis_run_id": run.id,
            "pipeline_version": run.pipeline_version, "started": True}


@router.get("/{video_id}/runs")
def list_runs(video_id: str, current_user: User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    """Analysis history. One run is current; the rest are kept so a result
    can always be traced to the pipeline version that produced it."""
    from app.models.runs import AnalysisRun

    video = _get_owned_video(db, video_id, current_user)
    runs = (db.query(AnalysisRun).filter_by(video_id=video.id)
            .order_by(AnalysisRun.created_at.desc()).all())
    return [{
        "id": r.id, "pipeline_version": r.pipeline_version, "status": r.status,
        "is_current": r.is_current, "attempt": r.attempt, "stage": r.stage,
        "progress_pct": r.progress_pct,
        "started_at": r.started_at, "completed_at": r.completed_at,
        "error_code": r.error_code, "error_message": r.error_message,
        "retryable": r.retryable, "failed_stage": r.failed_stage,
        "configuration": r.configuration, "metrics": r.metrics,
    } for r in runs]


@router.get("/{video_id}/events")
def list_events(video_id: str, current_user: User = Depends(get_current_user),
                db: Session = Depends(get_db)):
    """Processing history for one video. Coarse by design — stage boundaries
    and incidents, never per-frame."""
    video = _get_owned_video(db, video_id, current_user)
    return [{
        "created_at": e.created_at, "event_type": e.event_type, "stage": e.stage,
        "progress_pct": e.progress_pct, "message": e.message,
        "duration_ms": e.duration_ms,
    } for e in events_service.history(db, video.id)]


@router.get("/{video_id}/stream")
def stream_video(video_id: str, token: str = Query(...)):
    # <video> elements can't set Authorization headers, so the stream endpoint
    # accepts the JWT as a query parameter instead of via get_current_user.
    db = SessionLocal()
    try:
        user = resolve_user_from_token(db, token)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        user_id = user.id
        video = db.get(Video, video_id)
        if not video:
            raise HTTPException(status_code=404, detail="Video not found")
        if video.owner_user_id != user_id:
            # Phase 4: a coach with an ACTIVE review on this exact video may
            # watch it — the only non-owner streaming path.
            from app.models.coach_review import CoachReview
            review = db.query(CoachReview).filter_by(
                video_id=video_id, coach_user_id=user_id, status="active"
            ).first()
            if not review:
                raise HTTPException(status_code=404, detail="Video not found")
        stored = Path(video.storage_path).resolve()
        if stored.parent != Path(UPLOADS_DIR).resolve() or not stored.exists():
            raise HTTPException(status_code=404, detail="Video file is no longer available")
        # `filename=` is omitted deliberately: Starlette would put it in a
        # Content-Disposition header, and the display name is user-controlled.
        return FileResponse(str(stored), media_type="video/mp4",
                            headers={"X-Content-Type-Options": "nosniff"})
    finally:
        db.close()


@router.post("/{video_id}/process")
def process_video(video_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    video = _get_owned_video(db, video_id, current_user)
    if video.status == "processing":
        return {"status": video.status}
    worker.submit(analysis_service.process_video, video_id)
    video.status = "processing"
    db.commit()
    return {"status": "processing"}


@router.get("/{video_id}/status")
def video_status(video_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    video = _get_owned_video(db, video_id, current_user)
    return {
        "status": video.status, "progress_pct": video.progress_pct,
        "stage": video.stage, "processing_error": video.processing_error,
    }


class TrackedPersonOut(BaseModel):
    id: str
    track_id: int
    role: str
    first_frame: int
    last_frame: int
    track_confidence: float
    sample_box: Optional[dict] = None

    class Config:
        from_attributes = True


@router.get("/{video_id}/tracked-persons", response_model=List[TrackedPersonOut])
def list_tracked_persons(video_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    video = _get_owned_video(db, video_id, current_user)
    persons = analysis_service.get_tracked_persons(db, video.id)
    out = []
    for p in persons:
        sample = p.bounding_boxes[len(p.bounding_boxes) // 2] if p.bounding_boxes else None
        out.append(TrackedPersonOut(
            id=p.id, track_id=p.track_id, role=p.role, first_frame=p.first_frame,
            last_frame=p.last_frame, track_confidence=p.track_confidence, sample_box=sample,
        ))
    return out


class ClaimRequest(BaseModel):
    role: str  # self/partner/opponent1/opponent2


@router.post("/{video_id}/tracked-persons/{tracked_person_id}/claim")
def claim_tracked_person(video_id: str, tracked_person_id: str, payload: ClaimRequest,
                          current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    video = _get_owned_video(db, video_id, current_user)
    ok = analysis_service.claim_tracked_person(db, video.id, tracked_person_id, payload.role)
    if not ok:
        raise HTTPException(status_code=404, detail="Tracked person not found")
    return {"claimed": True}


@router.get("/{video_id}/calibration")
def get_calibration(video_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    video = _get_owned_video(db, video_id, current_user)
    cal = db.query(Calibration).filter_by(video_id=video.id).first()
    if not cal:
        raise HTTPException(status_code=404, detail="No calibration available yet")
    return {
        "method": cal.method, "court_corners_px": cal.court_corners_px,
        "confidence": cal.confidence, "notes": cal.notes,
    }


@router.get("/{video_id}/rallies")
def list_rallies(video_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    video = _get_owned_video(db, video_id, current_user)
    rallies = db.query(Rally).filter_by(video_id=video.id).order_by(Rally.rally_index).all()
    return [{
        "rally_index": r.rally_index, "start_timestamp_s": r.start_timestamp_s,
        "end_timestamp_s": r.end_timestamp_s, "shot_count": r.shot_count, "confidence": r.confidence,
    } for r in rallies]


@router.get("/{video_id}/shots")
def list_shots(video_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    video = _get_owned_video(db, video_id, current_user)
    shots = db.query(Shot).filter_by(video_id=video.id).order_by(Shot.timestamp_s).all()
    return [{
        "timestamp_s": s.timestamp_s, "shot_type": s.shot_type, "side": s.side,
        "contact_height": s.contact_height, "intent": s.intent, "outcome": s.outcome,
        "confidence": s.confidence, "tracked_person_id": s.tracked_person_id,
    } for s in shots]


@router.get("/{video_id}/insights")
def list_insights(video_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    video = _get_owned_video(db, video_id, current_user)
    insights = db.query(CoachingInsight).filter_by(video_id=video.id).order_by(CoachingInsight.timestamp_s).all()
    return [{
        "timestamp_s": i.timestamp_s, "category": i.category, "observed_action": i.observed_action,
        "likely_impact": i.likely_impact, "correction": i.correction, "drill_id": i.drill_id,
        "confidence": i.confidence, "limitations": i.limitations,
    } for i in insights]


@router.get("/{video_id}/overlay-manifest")
def overlay_manifest(video_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Rebuilt from persisted rows so overlays survive server restarts."""
    from app.services.cv_pipeline.types import CalibrationResult, ShuttlePoint
    from app.models.analysis import ShuttleFrame

    video = _get_owned_video(db, video_id, current_user)
    homography, cal = analysis_service.homography_from_db(db, video.id)
    if cal is None:
        raise HTTPException(status_code=404, detail="No analysis data exists yet for this video.")

    calibration = CalibrationResult(
        method=cal.method, court_corners_px=cal.court_corners_px or [],
        homography=homography, confidence=cal.confidence, notes=cal.notes or "",
    )
    persons = analysis_service.get_tracked_persons(db, video.id)
    tracks = [analysis_service.rebuild_track_from_db(tp) for tp in persons]
    poses = []
    for tp in persons:
        poses.extend(analysis_service.pose_samples_from_db(db, tp))
    shuttle_points = [
        ShuttlePoint(frame_index=s.frame_index, timestamp_s=s.timestamp_s,
                     x_px=(s.position_px or {}).get("x", 0), y_px=(s.position_px or {}).get("y", 0),
                     confidence=s.confidence)
        for s in db.query(ShuttleFrame).filter_by(video_id=video.id).order_by(ShuttleFrame.frame_index).all()
    ]
    return build_overlay_manifest(calibration, tracks, poses, shuttle_points)


@router.get("/{video_id}/heatmap")
def heatmap(video_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Rebuilt from persisted rows so heatmaps survive server restarts."""
    from app.services.cv_pipeline import tactics as tactics_mod

    video = _get_owned_video(db, video_id, current_user)
    homography, cal = analysis_service.homography_from_db(db, video.id)
    if homography is None:
        raise HTTPException(status_code=404, detail="Heatmaps need a court calibration, which is unavailable for this video.")

    result = {}
    for tp in analysis_service.get_tracked_persons(db, video.id):
        track = analysis_service.rebuild_track_from_db(tp)
        result[str(tp.track_id)] = {"heatmap": tactics_mod.build_heatmap(track, homography, cal.confidence)}
    return result


@router.get("/{video_id}/scorecards")
def scorecards(video_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """V2 technique scorecards: ten dimensions, each with score, confidence,
    and the proxy it was computed from. Rebuilt entirely from persisted rows
    so it survives server restarts."""
    from app.services.cv_pipeline import biomechanics as biomech_mod
    from app.services.cv_pipeline import tactics as tactics_mod
    from app.core.config import FRAME_SAMPLE_FPS

    video = _get_owned_video(db, video_id, current_user)
    self_tp = db.query(TrackedPerson).filter_by(video_id=video.id, role="self").first()
    if not self_tp:
        raise HTTPException(status_code=404, detail="Scorecards appear after you confirm which player is you.")

    pose_samples = analysis_service.pose_samples_from_db(db, self_tp)
    frames = biomech_mod.analyze_pose_sequence(pose_samples)
    pose_by_frame = {p.frame_index: p.landmarks for p in pose_samples}

    shots = db.query(Shot).filter_by(video_id=video.id, tracked_person_id=self_tp.id).all()
    rally_index_by_id = {r.id: r.rally_index for r in db.query(Rally).filter_by(video_id=video.id).all()}
    self_shots = [{
        "frame_index": s.frame_index, "timestamp_s": s.timestamp_s,
        "rally_index": rally_index_by_id.get(s.rally_id, 0),
        "contact_height": s.contact_height, "shot_type": s.shot_type, "confidence": s.confidence,
    } for s in shots]

    positions = analysis_service.court_positions_from_db(db, video.id, self_tp)
    avg_recovery = None
    homography, _ = analysis_service.homography_from_db(db, video.id)
    if homography is not None:
        track = analysis_service.rebuild_track_from_db(self_tp)
        recovery = tactics_mod.estimate_recovery_times(track, homography, [s["timestamp_s"] for s in self_shots], FRAME_SAMPLE_FPS)
        avg_recovery = recovery.get("average_recovery_s")

    return compute_technique_scores(
        biomech_frames=frames, pose_by_frame=pose_by_frame, self_shots=self_shots,
        avg_recovery_s=avg_recovery, positions=positions,
    )


@router.get("/{video_id}/quality-report")
def quality_report(video_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    video = _get_owned_video(db, video_id, current_user)
    if not video.quality_report:
        raise HTTPException(status_code=404, detail="No quality report yet — it is generated when processing starts.")
    return {
        "score": video.quality_score,
        "pipeline_version": video.pipeline_version,
        **video.quality_report,
    }


@router.get("/{video_id}/phases")
def rally_phases_timeline(video_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    video = _get_owned_video(db, video_id, current_user)
    rallies = db.query(Rally).filter_by(video_id=video.id).order_by(Rally.rally_index).all()
    return [{
        "rally_index": r.rally_index,
        "start_timestamp_s": r.start_timestamp_s,
        "end_timestamp_s": r.end_timestamp_s,
        "shot_count": r.shot_count,
        "confidence": r.confidence,
        "phases": r.phases or [],
        "ending_shot_type": r.ending_shot_type,
        "ending_track_role": r.ending_track_role,
    } for r in rallies]


@router.get("/{video_id}/analytics")
def match_analytics(video_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    video = _get_owned_video(db, video_id, current_user)
    row = db.query(MatchAnalytics).filter_by(video_id=video.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Match analytics are generated after you confirm which player is you.")
    return row.analytics


@router.get("/compare/{video_a}/{video_b}")
def compare_matches(video_a: str, video_b: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Side-by-side stat comparison of two of the user's analyzed matches."""
    a = _get_owned_video(db, video_a, current_user)
    b = _get_owned_video(db, video_b, current_user)

    def summarize(video: Video):
        analytics_row = db.query(MatchAnalytics).filter_by(video_id=video.id).first()
        blocks = (analytics_row.analytics.get("blocks", {}) if analytics_row else {})
        rally_stats = blocks.get("rally_stats", {})
        mix = blocks.get("shot_mix", {})
        dominance = blocks.get("court_dominance", {})
        return {
            "video_id": video.id,
            "filename": video.original_filename,
            "opponent_name": video.opponent_name,
            "result_summary": video.result_summary,
            "quality_score": video.quality_score,
            "rally_count": rally_stats.get("rally_count"),
            "avg_rally_duration_s": rally_stats.get("avg_duration_s"),
            "avg_shots_per_rally": rally_stats.get("avg_shots_per_rally"),
            "total_shots": mix.get("total_shots"),
            "shot_variety": mix.get("shot_variety"),
            "offensive_pct": (mix.get("by_intent") or {}).get("offensive"),
            "defensive_pct": (mix.get("by_intent") or {}).get("defensive"),
            "front_court_pct": dominance.get("front_court_pct"),
            "confidence_note": "Stats derive from heuristic tracking — compare directions, not decimals.",
        }

    return {"a": summarize(a), "b": summarize(b)}


class CalibrationCorrection(BaseModel):
    court_corners_px: list  # [[x,y] * 4] in TL,TR,BR,BL order


@router.patch("/{video_id}/calibration")
def correct_calibration(video_id: str, payload: CalibrationCorrection,
                        current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Manual court-corner correction: recomputes the homography, marks the
    calibration user-corrected, and stores the correction as feedback."""
    video = _get_owned_video(db, video_id, current_user)
    if len(payload.court_corners_px) != 4:
        raise HTTPException(status_code=400, detail="Exactly 4 corners required (TL, TR, BR, BL).")

    cal = db.query(Calibration).filter_by(video_id=video.id).first()
    if not cal:
        raise HTTPException(status_code=404, detail="No calibration exists to correct.")

    homography = solve_homography_from_corners(payload.court_corners_px)
    cal.method = "manual"
    cal.court_corners_px = payload.court_corners_px
    cal.homography_matrix = homography.tolist() if homography is not None else None
    cal.confidence = 0.85  # user-placed corners are trusted more than auto-detection, but still single-view
    cal.notes = "Corners manually corrected by the user."

    db.add(UserCorrection(
        user_id=current_user.id, video_id=video.id, correction_type="court_corners",
        payload={"court_corners_px": payload.court_corners_px}, applied=True,
    ))
    db.commit()

    # Keep the in-process cache consistent so heatmaps/analytics recompute against the fix.
    cached = analysis_service._pipeline_cache.get(video.id)
    if cached is not None and homography is not None:
        cached.calibration.court_corners_px = payload.court_corners_px
        cached.calibration.homography = homography
        cached.calibration.method = "manual"
        cached.calibration.confidence = 0.85

    return {"corrected": True, "confidence": 0.85}


def _may_read_video(db: Session, video_id: str, user_id: str) -> bool:
    """Ownership, or an ACTIVE coach review on this exact video.

    The only non-owner read path in the product. Scoped to one video, granted
    explicitly, and revoked the instant the review status changes — which is
    also what `soft_delete_video` relies on.
    """
    video = db.get(Video, video_id)
    if video is None or video.deleted_at is not None:
        return False
    if video.owner_user_id == user_id:
        return True
    from app.models.coach_review import CoachReview
    return db.query(CoachReview).filter_by(
        video_id=video_id, coach_user_id=user_id, status="active").first() is not None


def _get_owned_video(db: Session, video_id: str, user: User,
                     allow_coach: bool = False) -> Video:
    video = db.get(Video, video_id)
    if not video or video.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Video not found")
    if video.owner_user_id != user.id:
        # 404 rather than 403 throughout: a 403 confirms the id exists, which
        # turns id enumeration into an existence oracle.
        if not (allow_coach and _may_read_video(db, video_id, user.id)):
            raise HTTPException(status_code=404, detail="Video not found")
    return video
