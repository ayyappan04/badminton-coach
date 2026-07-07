"""Heuristic shot recognition: finds swing events from wrist-speed peaks in
the pose stream, then classifies coarse shot properties from simple
geometric rules (contact height from wrist-vs-shoulder height, side from
wrist-vs-torso position, shot type from swing speed + contact height +
vertical swing direction).

This rule-based approach is the Phase-0/MVP stand-in for a trained temporal
shot classifier (Phase 2, see docs/ROADMAP.md). It deliberately avoids
inventing shot categories it can't support with the available signals —
anything ambiguous is labeled "unknown" with reduced confidence rather than
guessed.
"""
from typing import List, Dict, Optional

from app.services.cv_pipeline.types import PoseSample, RallySegment, ShotEvent

WRIST_NAMES = {"left": "left_wrist", "right": "right_wrist"}
SHOULDER_NAMES = {"left": "left_shoulder", "right": "right_shoulder"}
HIP_NAMES = {"left": "left_hip", "right": "right_hip"}


def _landmark(sample: PoseSample, name: str) -> Optional[Dict[str, float]]:
    for lm in sample.landmarks:
        if lm["name"] == name:
            return lm
    return None


def _dominant_side_guess(samples: List[PoseSample]) -> str:
    """Without explicit user input, guess dominant hand as whichever wrist
    shows more movement variance across the match — a weak proxy, clearly
    documented as a guess. The product should let the user confirm/override this."""
    variance = {"left": 0.0, "right": 0.0}
    for side, wrist_name in WRIST_NAMES.items():
        xs = [_landmark(s, wrist_name)["x"] for s in samples if _landmark(s, wrist_name)]
        if len(xs) > 1:
            mean = sum(xs) / len(xs)
            variance[side] = sum((x - mean) ** 2 for x in xs) / len(xs)
    return "right" if variance["right"] >= variance["left"] else "left"


def recognize_shots(poses_by_track: Dict[int, List[PoseSample]], rallies: List[RallySegment]) -> List[ShotEvent]:
    shots: List[ShotEvent] = []

    for track_id, samples in poses_by_track.items():
        samples = sorted(samples, key=lambda s: s.frame_index)
        if len(samples) < 3:
            continue
        dominant = _dominant_side_guess(samples)
        wrist_name = WRIST_NAMES[dominant]
        shoulder_name = SHOULDER_NAMES[dominant]
        hip_name = HIP_NAMES[dominant]

        speeds = []
        for a, b in zip(samples, samples[1:]):
            wa, wb = _landmark(a, wrist_name), _landmark(b, wrist_name)
            dt = b.timestamp_s - a.timestamp_s
            if wa and wb and dt > 0:
                dist = ((wb["x"] - wa["x"]) ** 2 + (wb["y"] - wa["y"]) ** 2) ** 0.5
                speeds.append((b, dist / dt))
            else:
                speeds.append((b, 0.0))

        if not speeds:
            continue
        max_speed = max(s for _, s in speeds) or 1e-6
        threshold = max_speed * 0.55

        for rally in rallies:
            rally_shots = 0
            i = 0
            while i < len(speeds):
                sample, speed = speeds[i]
                in_rally = rally.start_timestamp_s <= sample.timestamp_s <= rally.end_timestamp_s
                if in_rally and speed >= threshold:
                    shot = _classify_shot(sample, speed, max_speed, wrist_name, shoulder_name, hip_name, dominant)
                    if shot:
                        shots.append(ShotEvent(
                            track_id=track_id, rally_index=rally.rally_index,
                            frame_index=sample.frame_index, timestamp_s=sample.timestamp_s,
                            shot_type=shot["shot_type"], side=shot["side"],
                            contact_height=shot["contact_height"], intent=shot["intent"],
                            outcome="unknown", confidence=shot["confidence"],
                        ))
                        rally_shots += 1
                    # skip ahead ~0.3s so one swing isn't counted as several peaks
                    j = i
                    while j < len(speeds) and speeds[j][0].timestamp_s - sample.timestamp_s < 0.3:
                        j += 1
                    i = j
                else:
                    i += 1

    return shots


def _classify_shot(sample: PoseSample, speed: float, max_speed: float, wrist_name: str, shoulder_name: str, hip_name: str, dominant: str) -> Optional[Dict]:
    wrist = _landmark(sample, wrist_name)
    shoulder = _landmark(sample, shoulder_name)
    hip = _landmark(sample, hip_name)
    if not wrist or not shoulder or not hip:
        return None

    # image y grows downward; "above shoulder" means wrist.y < shoulder.y
    contact_height = "overhead" if wrist["y"] < shoulder["y"] else "underhand"
    side = "forehand" if dominant == "right" else "backhand"  # simplistic proxy pending racket-tracking (Phase 2)

    speed_ratio = speed / max_speed
    if contact_height == "overhead":
        if speed_ratio > 0.85:
            shot_type, intent = "smash", "offensive"
        elif speed_ratio > 0.6:
            shot_type, intent = "clear", "neutral"
        else:
            shot_type, intent = "drop", "offensive"
    else:
        if speed_ratio > 0.8:
            shot_type, intent = "drive", "offensive"
        elif speed_ratio > 0.55:
            shot_type, intent = "lift", "defensive"
        else:
            shot_type, intent = "net_shot", "neutral"

    base_confidence = min(sample.confidence, 0.7)  # shot-type confidence never exceeds pose confidence
    confidence = round(max(0.2, base_confidence * (0.6 + 0.4 * speed_ratio)), 2)

    return {"shot_type": shot_type, "side": side, "contact_height": contact_height, "intent": intent, "confidence": confidence}
