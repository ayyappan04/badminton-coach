"""Builds a per-frame overlay manifest (JSON, not baked into video) consumed by
the frontend canvas layer, so users can toggle individual overlays (skeleton,
court lines, shuttle trail, tracked boxes) independently, synced to the
<video> element's playback time.
"""
from typing import Dict, List

from app.services.cv_pipeline.types import CalibrationResult, Track, PoseSample, ShuttlePoint


def build_overlay_manifest(
    calibration: CalibrationResult,
    tracks: List[Track],
    poses: List[PoseSample],
    shuttle_points: List[ShuttlePoint],
) -> Dict:
    poses_by_frame: Dict[int, List[Dict]] = {}
    for p in poses:
        poses_by_frame.setdefault(p.frame_index, []).append({
            "track_id": p.track_id,
            "landmarks": p.landmarks,
            "confidence": p.confidence,
        })

    boxes_by_frame: Dict[int, List[Dict]] = {}
    for track in tracks:
        for box in track.boxes:
            boxes_by_frame.setdefault(box.frame_index, []).append({
                "track_id": track.track_id,
                "role": track.role,
                "x": box.x, "y": box.y, "w": box.w, "h": box.h,
                "confidence": box.confidence,
            })

    shuttle_by_frame: Dict[int, Dict] = {
        sp.frame_index: {"x": sp.x_px, "y": sp.y_px, "confidence": sp.confidence}
        for sp in shuttle_points
    }

    return {
        "court": {
            "corners_px": calibration.court_corners_px,
            "method": calibration.method,
            "confidence": calibration.confidence,
        },
        "boxes_by_frame": boxes_by_frame,
        "poses_by_frame": poses_by_frame,
        "shuttle_by_frame": shuttle_by_frame,
        "shuttle_trail": [{"frame_index": sp.frame_index, "x": sp.x_px, "y": sp.y_px} for sp in shuttle_points],
    }
