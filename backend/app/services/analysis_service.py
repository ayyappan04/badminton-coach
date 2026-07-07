"""Integration layer: runs the CV pipeline for a video, persists results to
the database, and (once the user has identified themselves) generates
coaching insights and refreshes the player's longitudinal profile.

Note on the in-memory pipeline cache: for the MVP, the full structured
PipelineResult (which keys biomechanics/tactics by the CV layer's integer
track IDs) is kept in an in-process cache alongside its DB-persisted rows,
because DB rows use UUID primary keys and re-deriving the richer structures
from rows alone isn't necessary for a single-process demo deployment. A
production deployment would persist an intermediate representation (or
recompute insights directly from DB rows) so this survives process restarts
and horizontal scaling.
"""
import traceback
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.video import Video, Calibration, TrackedPerson
from app.models.analysis import PoseFrame, ShuttleFrame, Rally, Shot, CoachingInsight, MatchAnalytics
from app.models.coaching_content import Drill
from app.models.profile import PlayerProfile, ProfileHistorySnapshot
from app.services.cv_pipeline.pipeline import run_pipeline, PIPELINE_VERSION
from app.services.cv_pipeline import rally_phases, court_geometry
from app.services.cv_pipeline.court_detection import pixel_to_court
from app.services.cv_pipeline.types import PipelineResult
from app.services.coaching import insight_generator
from app.services.tactics import match_analytics as analytics_engine
from app.services.tactics import doubles_rotation
from app.services.profiling import player_profile_builder as profiler

_pipeline_cache: Dict[str, PipelineResult] = {}
_track_id_map_cache: Dict[str, Dict[int, str]] = {}  # video_id -> {raw_track_id: tracked_person.id}


def process_video(video_id: str) -> None:
    db = SessionLocal()
    try:
        video = db.get(Video, video_id)
        if not video:
            return
        video.status = "processing"
        video.progress_pct = 0
        db.commit()

        def progress_cb(pct: int, stage: str):
            video.progress_pct = pct
            video.stage = stage
            db.commit()

        try:
            result = run_pipeline(video.storage_path, progress_cb=progress_cb)
        except Exception as exc:  # noqa: BLE001 — surface any CV failure as a user-facing processing error
            video.status = "failed"
            video.processing_error = f"{type(exc).__name__}: {exc}"
            db.commit()
            traceback.print_exc()
            return

        video.duration_seconds = result.meta.duration_s
        video.fps = result.meta.fps
        video.resolution_w = result.meta.width
        video.resolution_h = result.meta.height
        video.pipeline_version = PIPELINE_VERSION
        if result.quality:
            video.quality_score = result.quality["score"]
            video.quality_report = result.quality

        _pipeline_cache[video_id] = result
        _persist_pipeline_result(db, video, result)

        if len(result.tracks) == 1:
            # unambiguous — auto-assign the only detected person as "self"
            tp = db.query(TrackedPerson).filter_by(video_id=video_id).first()
            if tp:
                tp.role = "self"
                db.commit()
                finalize_after_identity(video_id)
                return

        video.status = "needs_player_selection" if result.tracks else "analyzed"
        if not result.tracks:
            video.processing_error = "No players could be reliably detected in this video. Try a clearer, more direct camera angle."
        db.commit()
    finally:
        db.close()


def _persist_pipeline_result(db: Session, video: Video, result: PipelineResult) -> None:
    cal = result.calibration
    db.add(Calibration(
        video_id=video.id, method=cal.method,
        homography_matrix=cal.homography.tolist() if cal.homography is not None else None,
        court_corners_px=cal.court_corners_px, confidence=cal.confidence, notes=cal.notes,
    ))

    track_id_map: Dict[int, str] = {}
    for track in result.tracks:
        tp = TrackedPerson(
            video_id=video.id, track_id=track.track_id, role=track.role,
            bounding_boxes=[{"frame_index": b.frame_index, "x": b.x, "y": b.y, "w": b.w, "h": b.h, "confidence": b.confidence} for b in track.boxes],
            first_frame=track.first_frame, last_frame=track.last_frame,
            track_confidence=track.mean_confidence,
        )
        db.add(tp)
        db.flush()
        track_id_map[track.track_id] = tp.id
    _track_id_map_cache[video.id] = track_id_map

    for pose in result.poses:
        tp_id = track_id_map.get(pose.track_id)
        if not tp_id:
            continue
        db.add(PoseFrame(
            tracked_person_id=tp_id, video_id=video.id, frame_index=pose.frame_index,
            timestamp_s=pose.timestamp_s, landmarks=pose.landmarks, confidence=pose.confidence,
        ))

    for sp in result.shuttle_points:
        db.add(ShuttleFrame(
            video_id=video.id, frame_index=sp.frame_index, timestamp_s=sp.timestamp_s,
            position_px={"x": sp.x_px, "y": sp.y_px}, confidence=sp.confidence,
        ))

    rally_id_map: Dict[int, str] = {}
    for rally in result.rallies:
        r = Rally(
            video_id=video.id, rally_index=rally.rally_index,
            start_frame=rally.start_frame, end_frame=rally.end_frame,
            start_timestamp_s=rally.start_timestamp_s, end_timestamp_s=rally.end_timestamp_s,
            shot_count=sum(1 for s in result.shots if s.rally_index == rally.rally_index),
            confidence=rally.confidence,
            phases=result.phases_by_rally.get(rally.rally_index, []),
        )
        db.add(r)
        db.flush()
        rally_id_map[rally.rally_index] = r.id

    for shot in result.shots:
        tp_id = track_id_map.get(shot.track_id)
        rally_id = rally_id_map.get(shot.rally_index)
        if not tp_id or not rally_id:
            continue
        db.add(Shot(
            rally_id=rally_id, video_id=video.id, tracked_person_id=tp_id,
            shot_index_in_rally=0, frame_index=shot.frame_index, timestamp_s=shot.timestamp_s,
            shot_type=shot.shot_type, side=shot.side, contact_height=shot.contact_height,
            intent=shot.intent, outcome=shot.outcome, confidence=shot.confidence,
        ))

    db.commit()


def get_tracked_persons(db: Session, video_id: str) -> List[TrackedPerson]:
    return db.query(TrackedPerson).filter_by(video_id=video_id).all()


# ---- DB-backed reconstruction (V2) ----
# The in-process pipeline cache does not survive server restarts, so the
# dashboard endpoints rebuild what they need from persisted rows instead of
# 404ing after a restart ("partial-result delivery", docs/V2_DESIGN.md §10).

def rebuild_track_from_db(tp: TrackedPerson):
    from app.services.cv_pipeline.types import Track, DetectionBox
    boxes = [
        DetectionBox(frame_index=b["frame_index"], x=b["x"], y=b["y"], w=b["w"], h=b["h"], confidence=b.get("confidence", 0.5))
        for b in (tp.bounding_boxes or [])
    ]
    return Track(track_id=tp.track_id, boxes=boxes, role=tp.role)


def homography_from_db(db: Session, video_id: str):
    import numpy as np
    cal = db.query(Calibration).filter_by(video_id=video_id).first()
    if not cal or not cal.homography_matrix:
        return None, cal
    return np.array(cal.homography_matrix), cal


def pose_samples_from_db(db: Session, tp: TrackedPerson):
    from app.services.cv_pipeline.types import PoseSample
    rows = db.query(PoseFrame).filter_by(tracked_person_id=tp.id).order_by(PoseFrame.frame_index).all()
    return [
        PoseSample(track_id=tp.track_id, frame_index=r.frame_index, timestamp_s=r.timestamp_s,
                   landmarks=r.landmarks, confidence=r.confidence)
        for r in rows
    ]


def court_positions_from_db(db: Session, video_id: str, tp: TrackedPerson) -> List[Dict]:
    from app.core.config import FRAME_SAMPLE_FPS
    homography, _ = homography_from_db(db, video_id)
    if homography is None:
        return []
    positions = []
    for b in (tp.bounding_boxes or []):
        try:
            x, y = pixel_to_court(homography, b["x"] + b["w"] / 2, b["y"] + b["h"])
        except Exception:
            continue
        positions.append({"timestamp_s": b["frame_index"] / FRAME_SAMPLE_FPS, "x": x, "y": y})
    return positions


def claim_tracked_person(db: Session, video_id: str, tracked_person_id: str, role: str) -> bool:
    tp = db.get(TrackedPerson, tracked_person_id)
    if not tp or tp.video_id != video_id:
        return False
    tp.role = role
    db.commit()

    if role == "self":
        finalize_after_identity(video_id)
    return True


def finalize_after_identity(video_id: str) -> None:
    db = SessionLocal()
    try:
        video = db.get(Video, video_id)
        if not video:
            return
        result = _pipeline_cache.get(video_id)
        track_id_map = _track_id_map_cache.get(video_id, {})
        tracked_persons = get_tracked_persons(db, video_id)
        self_tp = next((tp for tp in tracked_persons if tp.role == "self"), None)
        if not self_tp or not result:
            video.status = "analyzed"
            db.commit()
            return

        reverse_map = {v: k for k, v in track_id_map.items()}
        self_track_id = reverse_map.get(self_tp.id)
        partner_tp = next((tp for tp in tracked_persons if tp.role == "partner"), None)
        opponent_track_ids = [
            reverse_map[tp.id] for tp in tracked_persons
            if tp.id != self_tp.id and (partner_tp is None or tp.id != partner_tp.id) and tp.id in reverse_map
        ]
        partner_track_id = reverse_map.get(partner_tp.id) if partner_tp else None

        insights = []
        if self_track_id is not None:
            insights = insight_generator.generate_insights(
                result, self_track_id, opponent_track_ids=opponent_track_ids, partner_track_id=partner_track_id
            )

        drills_by_tag: Dict[str, str] = {}
        for d in db.query(Drill).all():
            for tag in (d.target_issue_tags or []):
                drills_by_tag.setdefault(tag, d.id)

        for insight in insights:
            drill_id = None
            for tag in insight.get("drill_tags", []):
                if tag in drills_by_tag:
                    drill_id = drills_by_tag[tag]
                    break
            db.add(CoachingInsight(
                video_id=video_id, tracked_person_id=self_tp.id,
                related_shot_id=None, timestamp_s=insight["timestamp_s"],
                category=insight["category"], observed_action=insight["observed_action"],
                likely_impact=insight["likely_impact"], correction=insight["correction"],
                drill_id=drill_id, confidence=insight["confidence"],
                limitations=insight.get("limitations", []),
            ))

        # V2: re-derive rally phases from the confirmed identity (attack/defense
        # are relative to the analyzed player) and persist ending events.
        if self_track_id is not None:
            role_by_track = {reverse_map[tp.id]: tp.role for tp in tracked_persons if tp.id in reverse_map}
            rally_rows = db.query(Rally).filter_by(video_id=video_id).all()
            rallies_by_index = {r.rally_index: r for r in rally_rows}
            for rally_seg in result.rallies:
                row = rallies_by_index.get(rally_seg.rally_index)
                if not row:
                    continue
                row.phases = rally_phases.analyze_rally_phases(rally_seg, result.shots, self_track_id)
                ending = rally_phases.ending_event(rally_seg, result.shots, role_by_track)
                row.ending_shot_type = ending["ending_shot_type"]
                row.ending_track_role = ending["ending_track_role"]
            db.commit()

            _compute_and_store_match_analytics(db, video, result, self_track_id, opponent_track_ids, partner_track_id)

        video.status = "analyzed"
        video.match_format = "doubles" if len(tracked_persons) > 2 else ("singles" if len(tracked_persons) == 2 else video.match_format)
        db.commit()

        update_player_profile(video.owner_user_id)
    finally:
        db.close()


def _court_positions_for_track(result: PipelineResult, track_id: int) -> List[Dict]:
    """Foot positions of a track mapped into court meters, where calibration allows."""
    if result.calibration.homography is None:
        return []
    track = next((t for t in result.tracks if t.track_id == track_id), None)
    if not track:
        return []
    positions = []
    from app.core.config import FRAME_SAMPLE_FPS
    for box in track.boxes:
        try:
            x, y = pixel_to_court(result.calibration.homography, box.x + box.w / 2, box.y + box.h)
        except Exception:
            continue
        positions.append({"timestamp_s": box.frame_index / FRAME_SAMPLE_FPS, "x": x, "y": y})
    return positions


def _compute_and_store_match_analytics(
    db: Session, video: Video, result: PipelineResult,
    self_track_id: int, opponent_track_ids: List[int],
    partner_track_id: Optional[int] = None,
) -> None:
    rallies_payload = [
        {"rally_index": r.rally_index, "start_s": r.start_timestamp_s, "end_s": r.end_timestamp_s}
        for r in result.rallies
    ]
    shots_payload = [
        {
            "rally_index": s.rally_index, "timestamp_s": s.timestamp_s, "frame_index": s.frame_index,
            "shot_type": s.shot_type, "intent": s.intent, "contact_height": s.contact_height,
            "confidence": s.confidence, "is_self": s.track_id == self_track_id,
        }
        for s in result.shots
    ]
    self_positions = _court_positions_for_track(result, self_track_id)
    opponent_heatmap = None
    if opponent_track_ids:
        opponent_heatmap = result.tactics.get(str(opponent_track_ids[0]), {}).get("heatmap")

    analytics = analytics_engine.compute_match_analytics(
        rallies=rallies_payload, shots=shots_payload, self_positions=self_positions,
        opponent_heatmap=opponent_heatmap, net_y=court_geometry.NET_Y,
        calibration_confidence=result.calibration.confidence,
    )

    if partner_track_id is not None:
        team_track_ids = {self_track_id, partner_track_id}
        team_shots = [
            {"timestamp_s": s.timestamp_s, "intent": s.intent, "is_self_team": s.track_id in team_track_ids}
            for s in result.shots
        ]
        self_track = next((t for t in result.tracks if t.track_id == self_track_id), None)
        track_conf = self_track.mean_confidence if self_track else 0.4
        analytics["blocks"]["doubles_rotation"] = doubles_rotation.analyze_doubles_rotation(
            self_positions=self_positions,
            partner_positions=_court_positions_for_track(result, partner_track_id),
            shots=team_shots,
            calibration_confidence=result.calibration.confidence,
            track_confidence=track_conf,
        )

    existing = db.query(MatchAnalytics).filter_by(video_id=video.id).first()
    if existing:
        existing.analytics = analytics
        existing.feature_version = analytics["feature_version"]
    else:
        db.add(MatchAnalytics(video_id=video.id, analytics=analytics, feature_version=analytics["feature_version"]))
    db.commit()


def update_player_profile(user_id: str) -> None:
    db = SessionLocal()
    try:
        videos = db.query(Video).filter_by(owner_user_id=user_id, status="analyzed").all()
        match_summaries = []
        for video in videos:
            self_tp = db.query(TrackedPerson).filter_by(video_id=video.id, role="self").first()
            if not self_tp:
                continue
            shots = db.query(Shot).filter_by(video_id=video.id, tracked_person_id=self_tp.id).all()
            shot_type_counts: Dict[str, int] = {}
            intent_counts: Dict[str, int] = {}
            for s in shots:
                shot_type_counts[s.shot_type] = shot_type_counts.get(s.shot_type, 0) + 1
                intent_counts[s.intent] = intent_counts.get(s.intent, 0) + 1

            poses = db.query(PoseFrame).filter_by(tracked_person_id=self_tp.id).all()
            stabilities = []
            cached = _pipeline_cache.get(video.id)
            if cached:
                for frame_list in cached.biomechanics.values():
                    stabilities.extend([f["stability_score"] for f in frame_list if f["stability_score"] is not None])
            avg_stability = sum(stabilities) / len(stabilities) if stabilities else None

            avg_recovery = None
            if cached:
                tp_data = cached.tactics.get(str(self_tp.track_id), {})
                recovery = tp_data.get("recovery")
                if recovery:
                    avg_recovery = recovery.get("average_recovery_s")

            rally_count = db.query(Rally).filter_by(video_id=video.id).count()

            match_summaries.append(profiler.summarize_match(
                shot_type_counts=shot_type_counts, intent_counts=intent_counts,
                avg_stability=avg_stability, avg_recovery_s=avg_recovery,
                rally_count=rally_count, formation_front_back_ratio=None,
                confidence=self_tp.track_confidence or 0.4,
            ))

        radar_scores = profiler.build_radar_scores(match_summaries)
        play_style = profiler.classify_play_style(match_summaries)
        sw = profiler.derive_strengths_and_weaknesses(radar_scores)
        training_plan = profiler.build_training_plan(sw["weaknesses"], play_style)

        profile = db.query(PlayerProfile).filter_by(user_id=user_id).first()
        if not profile:
            profile = PlayerProfile(user_id=user_id)
            db.add(profile)

        profile.matches_analyzed_count = len(match_summaries)
        profile.play_style_labels = play_style
        profile.strengths = sw["strengths"]
        profile.weaknesses = sw["weaknesses"]
        profile.radar_scores = radar_scores
        profile.training_plan = training_plan
        db.commit()

        latest_video_id = videos[-1].id if videos else None
        if latest_video_id:
            db.add(ProfileHistorySnapshot(user_id=user_id, video_id=latest_video_id, radar_scores=radar_scores))
            db.commit()
    finally:
        db.close()
