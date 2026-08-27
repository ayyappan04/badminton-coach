"""Integration layer: runs the CV pipeline for a video, persists results to
the database, and (once the user has identified themselves) generates
coaching insights and refreshes the player's longitudinal profile.

Note on the pipeline cache: the full structured PipelineResult keys
biomechanics/tactics by the CV layer's integer track IDs, which DB rows (UUID
primary keys) do not preserve. It is held in an in-process dict as a fast
path, and — since the production migration — also written to object storage as
a gzipped artifact by `pipeline_artifacts`. A cache miss therefore rehydrates
instead of silently degrading, which is what makes `finalize_after_identity`
produce the same analysis whether or not the worker that ran the pipeline is
the worker that finishes the job.
"""
import traceback
from collections import OrderedDict
from typing import Dict, List, Optional

from app.core import config

from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.video import Video, Calibration, TrackedPerson
from app.models.analysis import PoseFrame, ShuttleFrame, Rally, Shot, CoachingInsight, MatchAnalytics
from app.models.coaching_content import Drill
from app.models.profile import PlayerProfile, ProfileHistorySnapshot
# Only the light modules are imported eagerly. `run_pipeline` pulls in OpenCV
# and MediaPipe, and `court_detection` pulls in OpenCV — about 250 MB of
# resident memory. The API process imports this module for its DB-reading
# helpers and never runs a pipeline, so those imports happen inside the
# functions that actually need them.
from app.services.cv_pipeline.version import PIPELINE_VERSION
from app.services.cv_pipeline import rally_phases, court_geometry
from app.services.cv_pipeline.types import PipelineResult
from app.services.coaching import insight_generator
from app.services.tactics import match_analytics as analytics_engine
from app.services.tactics import doubles_rotation
from app.services.profiling import player_profile_builder as profiler

class _BoundedCache:
    """LRU cache for PipelineResults.

    Each entry is tens of megabytes. Unbounded, a long-lived API process
    accumulates one per video it has ever served and eventually OOMs -- the
    same failure mode the frame-budget work fixed inside the pipeline.

    Wraps an OrderedDict rather than subclassing it: overriding __getitem__ on
    a subclass makes eviction recurse back through the override.
    """

    def __init__(self, max_entries: int):
        self._data: "OrderedDict[str, PipelineResult]" = OrderedDict()
        self.max_entries = max(1, max_entries)

    def get(self, key, default=None):
        if key not in self._data:
            return default
        self._data.move_to_end(key)
        return self._data[key]

    def __getitem__(self, key):
        value = self.get(key)
        if value is None:
            raise KeyError(key)
        return value

    def __setitem__(self, key, value) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)

    def __contains__(self, key) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)

    def pop(self, key, default=None):
        return self._data.pop(key, default)

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def clear(self) -> None:
        self._data.clear()


_pipeline_cache: "_BoundedCache" = _BoundedCache(config.PIPELINE_CACHE_MAX_ENTRIES)
_track_id_map_cache: Dict[str, Dict[int, str]] = {}  # video_id -> {raw_track_id: tracked_person.id}


def process_video(video_id: str, source_path: Optional[str] = None,
                  run=None, workdir=None, progress_cb=None) -> None:
    """Run the CV pipeline for one video and persist the results.

    `source_path` is the local analysis proxy the worker downloaded. It falls
    back to `video.storage_path` so the pre-migration local flow, and its
    tests, keep working unchanged.
    """
    db = SessionLocal()
    try:
        video = db.get(Video, video_id)
        if not video:
            return
        if video.status not in ("processing", "queued", "normalizing"):
            video.status = "processing"
        video.progress_pct = max(video.progress_pct or 0, 0)
        db.commit()

        def _progress(pct: int, stage: str):
            video.progress_pct = pct
            video.stage = stage
            db.commit()
            if progress_cb:
                progress_cb(pct, stage)

        # Imported here, not at module scope: this is the only place the CV
        # stack is needed, and the API process must not pay for it.
        from app.services.cv_pipeline.pipeline import run_pipeline

        media_path = source_path or video.storage_path
        try:
            result = run_pipeline(media_path, progress_cb=_progress)
        except Exception as exc:  # noqa: BLE001 — surface any CV failure as a user-facing processing error
            video.status = "failed"
            video.processing_error = f"{type(exc).__name__}: {exc}"
            db.commit()
            traceback.print_exc()
            raise

        video.duration_seconds = result.meta.duration_s
        video.fps = result.meta.fps
        video.resolution_w = result.meta.width
        video.resolution_h = result.meta.height
        video.pipeline_version = PIPELINE_VERSION
        if result.quality:
            video.quality_score = result.quality["score"]
            video.quality_report = result.quality

        video.analysis_confidence = _overall_confidence(result)
        _pipeline_cache[video_id] = result

        # Publish FIRST, then decide whether the landmarks still need a row
        # each. Skipping persistence on the assumption an upload succeeded
        # would lose the data outright if it did not.
        artifact_published = _publish_artifact(video, result, workdir)
        store_landmarks = config.PERSIST_POSE_LANDMARKS or not artifact_published
        _persist_pipeline_result(db, video, result, store_landmarks=store_landmarks)

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


def _persist_pipeline_result(db: Session, video: Video, result: PipelineResult,
                             store_landmarks: bool = True) -> None:
    """Write CV output to relational rows.

    `store_landmarks=False` keeps the small queryable pose columns and leaves
    the 33-landmark payload in the gzipped artifact. Callers must only pass
    False once that artifact is confirmed published.
    """
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
            timestamp_s=pose.timestamp_s,
            landmarks=pose.landmarks if store_landmarks else [],
            confidence=pose.confidence,
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
    """Pose samples reconstructed from relational rows alone.

    Returns empty landmark lists for videos analyzed with
    PERSIST_POSE_LANDMARKS=false. Prefer `pose_samples_for`, which resolves
    them from whichever store actually holds them.
    """
    from app.services.cv_pipeline.types import PoseSample
    rows = db.query(PoseFrame).filter_by(tracked_person_id=tp.id).order_by(PoseFrame.frame_index).all()
    return [
        PoseSample(track_id=tp.track_id, frame_index=r.frame_index, timestamp_s=r.timestamp_s,
                   landmarks=r.landmarks or [], confidence=r.confidence)
        for r in rows
    ]


def pose_samples_for(db: Session, video: Video, tp: TrackedPerson):
    """Pose samples WITH landmarks, from wherever they live.

    Landmarks are ~76x cheaper in the gzipped artifact than as one JSON column
    per frame, so new analyses keep them there. This accessor hides that: it
    tries the in-process cache, then the artifact, then falls back to the rows
    themselves for videos analyzed before the change.
    """
    cached = _pipeline_cache.get(video.id) or _rehydrate(video)
    if cached is not None:
        samples = [p for p in cached.poses if p.track_id == tp.track_id]
        if samples:
            return sorted(samples, key=lambda p: p.frame_index)

    rows = pose_samples_from_db(db, tp)
    if any(r.landmarks for r in rows):
        return rows

    # Nothing has landmarks. Real for a video whose artifact upload failed AND
    # whose rows were written without them -- report it rather than silently
    # scoring against empty skeletons.
    if rows:
        import logging
        logging.getLogger("app.analysis").warning(
            "no pose landmarks available for video %s track %s", video.id, tp.track_id)
    return rows


def court_positions_from_db(db: Session, video_id: str, tp: TrackedPerson) -> List[Dict]:
    from app.core.config import FRAME_SAMPLE_FPS
    homography, _ = homography_from_db(db, video_id)
    if homography is None:
        return []
    from app.services.cv_pipeline.court_detection import pixel_to_court

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
        result = _pipeline_cache.get(video_id) or _rehydrate(video)
        track_id_map = _track_id_map_cache.get(video_id) or _rebuild_track_id_map(db, video_id)
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
    from app.services.cv_pipeline.court_detection import pixel_to_court

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
            cached = _pipeline_cache.get(video.id) or _rehydrate(video)
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


# ---------------------------------------------------------------------------
# Durable PipelineResult handling
# ---------------------------------------------------------------------------

def _publish_artifact(video: Video, result: PipelineResult, workdir=None) -> bool:
    """Write the full PipelineResult to object storage. Returns success.

    The return value is load-bearing: it decides whether the per-frame
    landmarks still need to be written to Postgres as well.
    """
    import tempfile
    from pathlib import Path
    try:
        from app.services import pipeline_artifacts
        target = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="ss-artifact-"))
        pipeline_artifacts.publish(
            result, user_id=video.owner_user_id, video_id=video.id,
            pipeline_version=PIPELINE_VERSION, workdir=target,
        )
        return True
    except Exception:  # noqa: BLE001
        import logging
        logging.getLogger("app.analysis").warning(
            "could not publish pipeline artifact for %s; "
            "falling back to storing pose landmarks in Postgres", video.id, exc_info=True)
        return False


def _rehydrate(video: Video) -> Optional[PipelineResult]:
    """Fetch the stored PipelineResult and repopulate the in-process cache."""
    try:
        from app.services import pipeline_artifacts
        result = pipeline_artifacts.fetch(
            user_id=video.owner_user_id, video_id=video.id,
            pipeline_version=video.pipeline_version or PIPELINE_VERSION,
        )
    except Exception:  # noqa: BLE001
        return None
    if result is not None:
        _pipeline_cache[video.id] = result
    return result


def _rebuild_track_id_map(db: Session, video_id: str) -> Dict[int, str]:
    """{raw CV track id: tracked_person UUID}, recovered from persisted rows."""
    mapping = {tp.track_id: tp.id for tp in get_tracked_persons(db, video_id)}
    if mapping:
        _track_id_map_cache[video_id] = mapping
    return mapping


def _overall_confidence(result: PipelineResult) -> Optional[float]:
    """A single 0-1 number for "how much should this analysis be trusted".

    Deliberately the mean of the measured signals rather than a fixed
    constant: calibration confidence, mean track confidence and mean pose
    confidence are the three things that actually determine whether the
    downstream numbers mean anything.
    """
    signals = []
    if result.calibration is not None:
        signals.append(float(result.calibration.confidence or 0.0))
    if result.tracks:
        signals.append(sum(t.mean_confidence for t in result.tracks) / len(result.tracks))
    if result.poses:
        signals.append(sum(p.confidence for p in result.poses) / len(result.poses))
    if not signals:
        return None
    return round(sum(signals) / len(signals), 4)
