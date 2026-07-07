"""Orchestrates the full CV pipeline for one uploaded video, stage by stage,
accumulating limitations/confidence along the way. See docs/CV_PIPELINE.md
and docs/V2_DESIGN.md for the stage diagrams this function implements.
"""
from typing import Callable, Dict, List, Optional

from app.core.config import FRAME_SAMPLE_FPS, MIN_RESOLUTION_FOR_SHUTTLE
from app.services.cv_pipeline import (
    frame_extraction, court_detection, player_tracking, pose_estimation,
    shuttle_detection, rally_segmentation, rally_phases, shot_recognition,
    biomechanics, tactics, video_quality,
)
from app.services.cv_pipeline.types import PipelineResult, PoseSample

PIPELINE_VERSION = "2.0.0"


def run_pipeline(video_path: str, progress_cb: Optional[Callable[[int, str], None]] = None) -> PipelineResult:
    def report(pct: int, stage: str):
        if progress_cb:
            progress_cb(pct, stage)

    report(2, "reading_video_metadata")
    meta = frame_extraction.read_video_meta(video_path)

    report(5, "assessing_video_quality")
    quality = video_quality.assess_video_quality(video_path)
    limitations: List[str] = []
    if quality["score"] < 50:
        limitations.append("low_video_quality")
    if quality["camera_cuts"]:
        limitations.append("camera_cuts_detected")
    if meta.fps and meta.fps < 24:
        limitations.append("low_frame_rate_source")

    if not quality["usable"]:
        # Unreadable/near-unusable footage: return the quality report so the
        # UI can explain what to fix, rather than emitting noise analysis.
        return PipelineResult(
            meta=meta,
            calibration=court_detection.detect_court([]),
            tracks=[], poses=[], shuttle_points=[], rallies=[], shots=[],
            biomechanics={}, tactics={},
            limitations=limitations + ["video_unusable_for_analysis"],
            quality=quality,
        )

    report(10, "extracting_frames")
    frames = list(frame_extraction.iter_frames(video_path, FRAME_SAMPLE_FPS))

    report(20, "detecting_court")
    calibration = court_detection.detect_court(frames)
    limitations.extend(calibration.limitations)

    report(32, "tracking_players")
    tracks = player_tracking.track_players(
        frames,
        camera_cut_timestamps=quality["camera_cuts"],
        fps_sampled=FRAME_SAMPLE_FPS,
    )
    if not tracks:
        limitations.append("no_players_detected")

    report(48, "estimating_pose")
    poses = pose_estimation.estimate_poses(frames, tracks)
    if not poses:
        limitations.append("no_pose_landmarks_detected")

    report(60, "detecting_shuttle")
    shuttle_points = shuttle_detection.detect_shuttle_track(
        frame_extraction.iter_frames_native(video_path), min_resolution=MIN_RESOLUTION_FOR_SHUTTLE
    )
    if not shuttle_points:
        limitations.append("shuttle_not_reliably_detected")

    report(70, "segmenting_rallies")
    rallies = rally_segmentation.segment_rallies(tracks, FRAME_SAMPLE_FPS)
    if not rallies:
        limitations.append("no_rallies_segmented")

    report(78, "recognizing_shots")
    poses_by_track: Dict[int, List[PoseSample]] = {}
    for p in poses:
        poses_by_track.setdefault(p.track_id, []).append(p)
    shots = shot_recognition.recognize_shots(poses_by_track, rallies)

    report(84, "analyzing_rally_phases")
    phases_by_rally: Dict[int, List[Dict]] = {}
    for rally in rallies:
        phases_by_rally[rally.rally_index] = rally_phases.analyze_rally_phases(rally, shots, self_track_id=None)

    report(88, "estimating_biomechanics")
    biomech: Dict = {}
    for track_id, samples in poses_by_track.items():
        biomech[str(track_id)] = biomechanics.analyze_pose_sequence(samples)

    report(94, "analyzing_tactics")
    tactics_result: Dict = {}
    if calibration.homography is not None and tracks:
        for track in tracks:
            tactics_result[str(track.track_id)] = {
                "heatmap": tactics.build_heatmap(track, calibration.homography, calibration.confidence),
            }
        if len(tracks) >= 2:
            shot_timestamps_by_track: Dict[int, List[float]] = {}
            for s in shots:
                shot_timestamps_by_track.setdefault(s.track_id, []).append(s.timestamp_s)
            for track in tracks:
                ts_list = shot_timestamps_by_track.get(track.track_id, [])
                tactics_result[str(track.track_id)]["recovery"] = tactics.estimate_recovery_times(
                    track, calibration.homography, ts_list, FRAME_SAMPLE_FPS
                )
    else:
        limitations.append("no_court_transform_available_for_tactics")

    report(100, "done")

    return PipelineResult(
        meta=meta, calibration=calibration, tracks=tracks, poses=poses,
        shuttle_points=shuttle_points, rallies=rallies, shots=shots,
        biomechanics=biomech, tactics=tactics_result, limitations=limitations,
        quality=quality, phases_by_rally=phases_by_rally,
    )
