"""Tactical pattern analysis: court occupancy heatmaps, dead-zone detection,
recovery-to-center timing, and doubles formation classification.

Operates on court-meter coordinates (after the homography transform), so
outputs are approximate to the extent the calibration itself is approximate —
see the `calibration_confidence` passed through into each result.
"""
from typing import Dict, List, Optional, Tuple

import numpy as np

from app.services.cv_pipeline.types import Track
from app.services.cv_pipeline import court_geometry as geo
from app.services.cv_pipeline.court_detection import pixel_to_court

GRID_COLS = 6
GRID_ROWS = 10


def _track_centers_court(track: Track, homography) -> List[Tuple[int, float, float]]:
    points = []
    for box in track.boxes:
        cx_px, cy_px = box.x + box.w / 2, box.y + box.h  # use foot position (bottom of box), not centroid, for court location
        try:
            cx, cy = pixel_to_court(homography, cx_px, cy_px)
        except Exception:
            continue
        points.append((box.frame_index, cx, cy))
    return points


def build_heatmap(track: Track, homography, calibration_confidence: float) -> Dict:
    points = _track_centers_court(track, homography)
    grid = np.zeros((GRID_ROWS, GRID_COLS))
    for _, x, y in points:
        col = int(min(max(x / geo.DOUBLES_WIDTH, 0), 0.999) * GRID_COLS)
        row = int(min(max(y / geo.COURT_LENGTH, 0), 0.999) * GRID_ROWS)
        grid[row, col] += 1

    total = grid.sum()
    normalized = (grid / total).tolist() if total > 0 else grid.tolist()

    dead_zones = []
    if total > 0:
        threshold = 0.01
        for r in range(GRID_ROWS):
            for c in range(GRID_COLS):
                if normalized[r][c] < threshold:
                    dead_zones.append({"row": r, "col": c})

    return {
        "grid_rows": GRID_ROWS, "grid_cols": GRID_COLS,
        "occupancy": normalized,
        "dead_zones": dead_zones,
        "sample_count": int(total),
        "confidence": round(calibration_confidence * (0.9 if total > 20 else 0.5), 2),
    }


def estimate_recovery_times(track: Track, homography, event_timestamps: List[float], fps_sampled: float) -> Dict:
    """For each event (e.g. a shot), estimate how long it takes the player to
    return to within a 'central' zone of the court afterward."""
    points = _track_centers_court(track, homography)
    if not points:
        return {"average_recovery_s": None, "samples": 0, "confidence": 0.0}

    center_x, center_y = geo.DOUBLES_WIDTH / 2, geo.COURT_LENGTH / 2
    center_radius = min(geo.DOUBLES_WIDTH, geo.COURT_LENGTH) * 0.18

    recoveries = []
    for ts in event_timestamps:
        start_frame = round(ts * fps_sampled)
        after = [p for p in points if p[0] >= start_frame]
        for frame_no, x, y in after:
            dist = ((x - center_x) ** 2 + (y - center_y) ** 2) ** 0.5
            if dist <= center_radius:
                recoveries.append((frame_no - start_frame) / fps_sampled)
                break

    if not recoveries:
        return {"average_recovery_s": None, "samples": 0, "confidence": 0.0}

    return {
        "average_recovery_s": round(sum(recoveries) / len(recoveries), 2),
        "samples": len(recoveries),
        "confidence": round(min(0.75, 0.3 + 0.05 * len(recoveries)), 2),
    }


def classify_doubles_formation(track_a: Track, track_b: Track, homography) -> Dict:
    """Front-back (attack) vs side-by-side (defense) formation, based on the
    two teammates' relative position along the court's length axis vs. width axis."""
    pts_a = {f: (x, y) for f, x, y in _track_centers_court(track_a, homography)}
    pts_b = {f: (x, y) for f, x, y in _track_centers_court(track_b, homography)}
    shared_frames = sorted(set(pts_a.keys()) & set(pts_b.keys()))
    if not shared_frames:
        return {"formation_by_frame": {}, "confidence": 0.0}

    formations = {}
    for f in shared_frames:
        ax, ay = pts_a[f]
        bx, by = pts_b[f]
        depth_gap = abs(ay - by)
        width_gap = abs(ax - bx)
        formations[f] = "front_back" if depth_gap > width_gap else "side_by_side"

    return {
        "formation_by_frame": formations,
        "front_back_ratio": round(sum(1 for v in formations.values() if v == "front_back") / len(formations), 2),
        "confidence": round(min(0.7, 0.25 + 0.01 * len(shared_frames)), 2),
    }
