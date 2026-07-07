"""Biomechanical feature estimation from 2D pose landmarks: joint angles,
stance classification, approximate center of mass, and a stability score.

Everything here is a single-camera, 2D-projection estimate. Without depth or
multi-camera triangulation, these are directional signals, not clinical
biomechanical measurements — every output keeps that framing in mind and
inherits the underlying pose sample's confidence.
"""
import math
from typing import Dict, List, Optional

from app.services.cv_pipeline.types import PoseSample

# Landmarks contributing to a coarse center-of-mass proxy, roughly weighted by
# the fraction of body mass near each region (simplified, not anthropometrically exact).
COM_WEIGHTS = {
    "left_hip": 0.15, "right_hip": 0.15,
    "left_shoulder": 0.12, "right_shoulder": 0.12,
    "left_knee": 0.10, "right_knee": 0.10,
    "left_ankle": 0.08, "right_ankle": 0.08,
    "nose": 0.10,
}


def _lm(sample: PoseSample, name: str) -> Optional[Dict[str, float]]:
    for l in sample.landmarks:
        if l["name"] == name:
            return l
    return None


def _angle(a, b, c) -> Optional[float]:
    """Angle at vertex b, formed by points a-b-c, in degrees."""
    if not (a and b and c):
        return None
    v1 = (a["x"] - b["x"], a["y"] - b["y"])
    v2 = (c["x"] - b["x"], c["y"] - b["y"])
    dot = v1[0] * v2[0] + v1[1] * v2[1]
    mag1 = math.hypot(*v1)
    mag2 = math.hypot(*v2)
    if mag1 == 0 or mag2 == 0:
        return None
    cos_angle = max(-1.0, min(1.0, dot / (mag1 * mag2)))
    return math.degrees(math.acos(cos_angle))


def estimate_center_of_mass(sample: PoseSample) -> Optional[Dict[str, float]]:
    total_w = 0.0
    cx, cy = 0.0, 0.0
    for name, weight in COM_WEIGHTS.items():
        lm = _lm(sample, name)
        if lm is None or lm["visibility"] < 0.3:
            continue
        cx += lm["x"] * weight
        cy += lm["y"] * weight
        total_w += weight
    if total_w == 0:
        return None
    return {"x": cx / total_w, "y": cy / total_w}


def estimate_stability(sample: PoseSample) -> Optional[float]:
    """0-1 score: how centered the estimated center of mass is over the base
    of support (the span between the two ankles). 1.0 = well balanced,
    0.0 = COM projected well outside the base of support."""
    com = estimate_center_of_mass(sample)
    left_ankle, right_ankle = _lm(sample, "left_ankle"), _lm(sample, "right_ankle")
    if not com or not left_ankle or not right_ankle:
        return None
    base_min_x = min(left_ankle["x"], right_ankle["x"])
    base_max_x = max(left_ankle["x"], right_ankle["x"])
    base_width = max(base_max_x - base_min_x, 0.02)  # avoid div-by-zero for feet together
    # allow some margin beyond the ankle span (real base of support extends past the ankles)
    margin = base_width * 0.6
    lo, hi = base_min_x - margin, base_max_x + margin
    if lo <= com["x"] <= hi:
        center = (lo + hi) / 2
        half_span = (hi - lo) / 2
        offset_ratio = abs(com["x"] - center) / half_span if half_span else 0
        return round(max(0.0, 1.0 - offset_ratio), 2)
    return round(0.0, 2)


def joint_angles(sample: PoseSample) -> Dict[str, Optional[float]]:
    return {
        "left_elbow": _angle(_lm(sample, "left_shoulder"), _lm(sample, "left_elbow"), _lm(sample, "left_wrist")),
        "right_elbow": _angle(_lm(sample, "right_shoulder"), _lm(sample, "right_elbow"), _lm(sample, "right_wrist")),
        "left_knee": _angle(_lm(sample, "left_hip"), _lm(sample, "left_knee"), _lm(sample, "left_ankle")),
        "right_knee": _angle(_lm(sample, "right_hip"), _lm(sample, "right_knee"), _lm(sample, "right_ankle")),
    }


def classify_stance(sample: PoseSample, prev_sample: Optional[PoseSample]) -> str:
    angles = joint_angles(sample)
    left_knee, right_knee = angles["left_knee"], angles["right_knee"]
    left_ankle, right_ankle = _lm(sample, "left_ankle"), _lm(sample, "right_ankle")
    hip = _lm(sample, "left_hip") or _lm(sample, "right_hip")

    if left_ankle is None or right_ankle is None or hip is None:
        return "unknown"

    foot_spread = abs(left_ankle["x"] - right_ankle["x"])
    avg_knee_bend = None
    knee_vals = [a for a in (left_knee, right_knee) if a is not None]
    if knee_vals:
        avg_knee_bend = sum(knee_vals) / len(knee_vals)

    # jump: both ankles significantly higher (smaller y) than in the previous sample
    if prev_sample is not None:
        prev_left_ankle, prev_right_ankle = _lm(prev_sample, "left_ankle"), _lm(prev_sample, "right_ankle")
        if prev_left_ankle and prev_right_ankle:
            avg_ankle_y = (left_ankle["y"] + right_ankle["y"]) / 2
            prev_avg_ankle_y = (prev_left_ankle["y"] + prev_right_ankle["y"]) / 2
            if prev_avg_ankle_y - avg_ankle_y > 0.04:  # normalized-frame-height jump threshold
                return "jump"

    if foot_spread > 0.22:
        return "lunge"
    if avg_knee_bend is not None and avg_knee_bend < 130:
        return "defensive"
    if avg_knee_bend is not None and avg_knee_bend < 160:
        return "attacking"
    return "neutral"


def analyze_pose_sequence(samples: List[PoseSample]) -> List[Dict]:
    samples = sorted(samples, key=lambda s: s.frame_index)
    results = []
    for i, sample in enumerate(samples):
        prev = samples[i - 1] if i > 0 else None
        results.append({
            "frame_index": sample.frame_index,
            "timestamp_s": sample.timestamp_s,
            "joint_angles": joint_angles(sample),
            "center_of_mass": estimate_center_of_mass(sample),
            "stability_score": estimate_stability(sample),
            "stance": classify_stance(sample, prev),
            "confidence": sample.confidence,
        })
    return results
