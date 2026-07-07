"""Technique scorecards v2: ten video-based technique dimensions, each with a
0-100 score, a confidence, and a `basis` string naming the proxy it was
computed from. These are estimates from 2D pose and tracking — the basis
strings keep the proxy visible to the user instead of implying direct
measurement.
"""
import statistics
from typing import Dict, List, Optional


def _score(v: float) -> float:
    return round(max(0.0, min(100.0, v * 100)), 1)


def _landmark(landmarks: List[Dict], name: str) -> Optional[Dict]:
    for lm in landmarks:
        if lm["name"] == name:
            return lm
    return None


def compute_technique_scores(
    biomech_frames: List[Dict],       # analyze_pose_sequence output for the player
    pose_by_frame: Dict[int, List[Dict]],  # frame_index -> landmarks list
    self_shots: List[Dict],           # [{frame_index, timestamp_s, rally_index, contact_height, shot_type, confidence}]
    avg_recovery_s: Optional[float],
    positions: List[Dict],            # [{timestamp_s, x, y}] court meters
) -> Dict[str, Dict]:
    scores: Dict[str, Dict] = {}

    stabilities = [f["stability_score"] for f in biomech_frames if f["stability_score"] is not None]
    active_stabilities = [
        f["stability_score"] for f in biomech_frames
        if f["stability_score"] is not None and f["stance"] in ("lunge", "jump", "attacking", "defensive")
    ]
    pose_conf = statistics.mean([f["confidence"] for f in biomech_frames]) if biomech_frames else 0.0

    # Footwork: balance quality specifically during dynamic movement stances.
    if active_stabilities:
        scores["footwork"] = {
            "score": _score(statistics.mean(active_stabilities)),
            "confidence": round(min(0.6, pose_conf), 2),
            "basis": "Video-based balance estimate during lunges, jumps, and loaded stances.",
        }
    else:
        scores["footwork"] = {"score": None, "confidence": 0.0, "basis": "No dynamic stances were tracked clearly enough."}

    # Balance: whole-match average of the center-of-mass-over-base estimate.
    if stabilities:
        scores["balance"] = {
            "score": _score(statistics.mean(stabilities)),
            "confidence": round(min(0.6, pose_conf), 2),
            "basis": "Average estimated center-of-mass position over the base of support (2D projection).",
        }
    else:
        scores["balance"] = {"score": None, "confidence": 0.0, "basis": "Pose landmarks were not reliable enough."}

    # Stability: worst-case rather than average — 10th percentile of balance.
    if len(stabilities) >= 10:
        sorted_stab = sorted(stabilities)
        p10 = sorted_stab[len(sorted_stab) // 10]
        scores["stability"] = {
            "score": _score(p10),
            "confidence": round(min(0.55, pose_conf), 2),
            "basis": "Your least stable tracked moments (10th percentile of the balance estimate).",
        }
    else:
        scores["stability"] = {"score": None, "confidence": 0.0, "basis": "Too few tracked frames."}

    # Racket preparation (proxy): dominant wrist held at/above hip height in
    # non-swing frames. Real racket detection is a Phase-3 model feature.
    prep_samples = []
    shot_frames = {s["frame_index"] for s in self_shots}
    for frame_index, landmarks in pose_by_frame.items():
        if frame_index in shot_frames:
            continue
        wrist = _landmark(landmarks, "right_wrist") or _landmark(landmarks, "left_wrist")
        hip = _landmark(landmarks, "right_hip") or _landmark(landmarks, "left_hip")
        if wrist and hip and wrist.get("visibility", 0) > 0.4:
            prep_samples.append(1.0 if wrist["y"] <= hip["y"] else 0.0)
    if len(prep_samples) >= 10:
        scores["racket_preparation"] = {
            "score": _score(statistics.mean(prep_samples)),
            "confidence": 0.4,
            "basis": "Share of between-shot frames with the racket hand at or above hip height (wrist proxy — racket itself is not tracked yet).",
        }
    else:
        scores["racket_preparation"] = {"score": None, "confidence": 0.0, "basis": "Too few between-shot frames with a visible racket hand."}

    # Contact height: overhead-type shots that were actually contacted overhead.
    overhead_types = {"smash", "clear", "drop"}
    overhead_shots = [s for s in self_shots if s["shot_type"] in overhead_types]
    if overhead_shots:
        good = sum(1 for s in overhead_shots if s["contact_height"] == "overhead")
        scores["contact_height"] = {
            "score": _score(good / len(overhead_shots)),
            "confidence": round(min(0.5, statistics.mean([s["confidence"] for s in overhead_shots])), 2),
            "basis": f"Of {len(overhead_shots)} smash/clear/drop swings, how many had an approximate contact point above shoulder height.",
        }
    else:
        scores["contact_height"] = {"score": None, "confidence": 0.0, "basis": "No overhead-type shots were tracked."}

    # Shot timing: consistency of intervals between consecutive shots in a rally.
    intervals = []
    by_rally: Dict[int, List[float]] = {}
    for s in sorted(self_shots, key=lambda s: s["timestamp_s"]):
        by_rally.setdefault(s["rally_index"], []).append(s["timestamp_s"])
    for times in by_rally.values():
        intervals.extend(b - a for a, b in zip(times, times[1:]) if 0 < b - a < 10)
    if len(intervals) >= 4:
        cv = statistics.stdev(intervals) / statistics.mean(intervals)
        scores["shot_timing"] = {
            "score": _score(max(0.0, 1.0 - cv * 0.8)),
            "confidence": 0.4,
            "basis": "Consistency of the rhythm between your consecutive shots (lower variation scores higher).",
        }
    else:
        scores["shot_timing"] = {"score": None, "confidence": 0.0, "basis": "Too few consecutive shots tracked."}

    # Recovery speed: average return-to-center time after shots.
    if avg_recovery_s is not None:
        scores["recovery_speed"] = {
            "score": _score(max(0.0, min(1.0, 1.3 - avg_recovery_s / 2.0))),
            "confidence": 0.5,
            "basis": f"Average of {round(avg_recovery_s, 2)}s to return toward a central position after shots (court-calibration dependent).",
        }
    else:
        scores["recovery_speed"] = {"score": None, "confidence": 0.0, "basis": "Recovery could not be measured (no court calibration)."}

    # Movement efficiency: steadiness of movement speed (erratic bursts and
    # stalls score lower than controlled, even movement).
    speeds = []
    for a, b in zip(positions, positions[1:]):
        dt = b["timestamp_s"] - a["timestamp_s"]
        if 0 < dt < 2:
            speeds.append((((b["x"] - a["x"]) ** 2 + (b["y"] - a["y"]) ** 2) ** 0.5) / dt)
    if len(speeds) >= 10 and statistics.mean(speeds) > 0:
        cv = statistics.stdev(speeds) / statistics.mean(speeds)
        scores["movement_efficiency"] = {
            "score": _score(max(0.0, 1.0 - cv * 0.4)),
            "confidence": 0.35,
            "basis": "Evenness of court movement speed — a proxy for economical footwork, not an energy measurement.",
        }
    else:
        scores["movement_efficiency"] = {"score": None, "confidence": 0.0, "basis": "Not enough court-mapped movement."}

    # Body alignment: shoulder line vs hip line horizontal offset at shot frames.
    alignments = []
    for s in self_shots:
        landmarks = pose_by_frame.get(s["frame_index"])
        if not landmarks:
            continue
        ls, rs = _landmark(landmarks, "left_shoulder"), _landmark(landmarks, "right_shoulder")
        lh, rh = _landmark(landmarks, "left_hip"), _landmark(landmarks, "right_hip")
        if ls and rs and lh and rh:
            shoulder_cx = (ls["x"] + rs["x"]) / 2
            hip_cx = (lh["x"] + rh["x"]) / 2
            alignments.append(abs(shoulder_cx - hip_cx))
    if alignments:
        scores["body_alignment"] = {
            "score": _score(max(0.0, 1.0 - statistics.mean(alignments) * 8)),
            "confidence": round(min(0.45, pose_conf), 2),
            "basis": "Estimated upper-body lean over the hips at your contact moments (2D projection — side lean and depth lean are not separable from one camera).",
        }
    else:
        scores["body_alignment"] = {"score": None, "confidence": 0.0, "basis": "Pose was not visible at shot moments."}

    # Execution consistency: how repeatable your balance is at contact.
    shot_stabilities = []
    biomech_by_frame = {f["frame_index"]: f for f in biomech_frames}
    for s in self_shots:
        f = biomech_by_frame.get(s["frame_index"])
        if f and f["stability_score"] is not None:
            shot_stabilities.append(f["stability_score"])
    if len(shot_stabilities) >= 4:
        spread = statistics.stdev(shot_stabilities)
        scores["execution_consistency"] = {
            "score": _score(max(0.0, 1.0 - spread * 2)),
            "confidence": 0.4,
            "basis": "How consistent your balance estimate is across shots — repeatable contact positions score higher.",
        }
    else:
        scores["execution_consistency"] = {"score": None, "confidence": 0.0, "basis": "Too few shots with clean pose tracking."}

    return scores
