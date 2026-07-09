import shutil
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import UPLOADS_DIR
from app.core.security import decode_access_token
from app.db.session import get_db, SessionLocal
from app.models.user import User
from app.models.video import Video, Calibration, TrackedPerson
from app.models.analysis import Rally, Shot, CoachingInsight, MatchAnalytics
from app.models.corrections import UserCorrection
from app.services import analysis_service
from app.services.cv_pipeline.overlay import build_overlay_manifest
from app.services.cv_pipeline.court_detection import solve_homography_from_corners
from app.services.coaching.technique_scores import compute_technique_scores
from app import worker

router = APIRouter(prefix="/videos", tags=["videos"])

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi"}


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

    class Config:
        from_attributes = True


@router.post("", response_model=VideoOut)
def upload_video(
    file: UploadFile = File(...),
    match_format: str = Form("unknown"),
    opponent_name: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{ext}'. Supported: {sorted(ALLOWED_EXTENSIONS)}")

    dest_name = f"{uuid.uuid4()}{ext}"
    dest_path = UPLOADS_DIR / dest_name
    with dest_path.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    video = Video(
        owner_user_id=current_user.id, storage_path=str(dest_path),
        original_filename=file.filename, match_format=match_format,
        opponent_name=opponent_name, status="uploaded",
    )
    db.add(video)
    db.commit()
    db.refresh(video)
    return video


@router.get("", response_model=List[VideoOut])
def list_videos(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return db.query(Video).filter_by(owner_user_id=current_user.id).order_by(Video.created_at.desc()).all()


@router.get("/{video_id}", response_model=VideoOut)
def get_video(video_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    video = _get_owned_video(db, video_id, current_user)
    return video


@router.delete("/{video_id}")
def delete_video(video_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    video = _get_owned_video(db, video_id, current_user)
    Path(video.storage_path).unlink(missing_ok=True)
    db.query(TrackedPerson).filter_by(video_id=video_id).delete()
    db.query(Calibration).filter_by(video_id=video_id).delete()
    db.query(Rally).filter_by(video_id=video_id).delete()
    db.query(Shot).filter_by(video_id=video_id).delete()
    db.query(CoachingInsight).filter_by(video_id=video_id).delete()
    db.delete(video)
    db.commit()
    return {"deleted": True}


@router.get("/{video_id}/stream")
def stream_video(video_id: str, token: str = Query(...)):
    # <video> elements can't set Authorization headers, so the stream endpoint
    # accepts the JWT as a query parameter instead of via get_current_user.
    user_id = decode_access_token(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    db = SessionLocal()
    try:
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
        return FileResponse(video.storage_path, media_type="video/mp4", filename=video.original_filename)
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


def _get_owned_video(db: Session, video_id: str, user: User) -> Video:
    video = db.get(Video, video_id)
    if not video or video.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="Video not found")
    return video
