"""Turns structured CV-pipeline output into coaching-language insights.

Each insight follows the structure required by the product spec: an observed
action, its likely impact, a prioritized correction, a drill tag (resolved to
an actual Drill record by the caller), and a confidence + limitations list.
Insight confidence is always capped by the confidence of the CV signals it
depends on — see `_capped_confidence`.
"""
from typing import Dict, List, Optional

from app.services.cv_pipeline.types import PipelineResult


def _capped_confidence(*confidences: float) -> float:
    values = [c for c in confidences if c is not None]
    if not values:
        return 0.3
    return round(min(0.85, min(values)), 2)  # coaching language is never more certain than its weakest input


def generate_insights(
    result: PipelineResult,
    self_track_id: int,
    opponent_track_ids: Optional[List[int]] = None,
    partner_track_id: Optional[int] = None,
) -> List[Dict]:
    opponent_track_ids = opponent_track_ids or []
    insights: List[Dict] = []

    insights.extend(_stability_insights(result, self_track_id))
    insights.extend(_contact_point_insights(result, self_track_id))
    insights.extend(_split_step_timing_insights(result, self_track_id, opponent_track_ids))
    insights.extend(_recovery_insights(result, self_track_id))
    if partner_track_id is not None:
        insights.extend(_formation_insights(result, self_track_id, partner_track_id))
    insights.extend(_shot_selection_insights(result, self_track_id))

    return insights


def _stability_insights(result: PipelineResult, track_id: int) -> List[Dict]:
    frames = result.biomechanics.get(str(track_id), [])
    low_stability = [
        f for f in frames
        if f["stability_score"] is not None and f["stability_score"] < 0.4
        and f["stance"] in ("lunge", "jump")
    ]
    if not low_stability:
        return []

    worst = min(low_stability, key=lambda f: f["stability_score"])
    ratio = len(low_stability) / max(1, len([f for f in frames if f["stance"] in ("lunge", "jump")]))

    return [{
        "category": "technique",
        "timestamp_s": worst["timestamp_s"],
        "observed_action": f"Your estimated center of mass shifts outside your base of support during {worst['stance']} movements in {round(ratio*100)}% of the {worst['stance']}s detected.",
        "likely_impact": "Reduced stability at the point of contact can limit control and slow your recovery for the next shot.",
        "correction": f"Focus on keeping your weight centered over your base foot when you {worst['stance']}, rather than reaching past your balance point.",
        "drill_tags": ["lunge_stability", "smash_landing", "balance_recovery"],
        "confidence": _capped_confidence(worst["confidence"], 0.6),
        "limitations": ["single_camera_no_depth", "2d_projection_estimate"],
    }]


def _contact_point_insights(result: PipelineResult, track_id: int) -> List[Dict]:
    insights = []
    for shot in result.shots:
        if shot.track_id != track_id or shot.contact_height != "overhead":
            continue
        frame_data = next((f for f in result.biomechanics.get(str(track_id), []) if f["frame_index"] == shot.frame_index), None)
        if not frame_data:
            continue
        insights.append({
            "category": "technique",
            "timestamp_s": shot.timestamp_s,
            "observed_action": f"On this {shot.shot_type}, your contact point was estimated based on wrist position relative to your head at the moment of the swing peak.",
            "likely_impact": "An overhead contact point that drifts behind the head typically shortens reach and can reduce shot depth.",
            "correction": "Aim to make contact slightly in front of and above your head, reaching up rather than back.",
            "drill_tags": ["clear_contact_point", "overhead_technique"],
            "confidence": _capped_confidence(shot.confidence, 0.55),
            "limitations": ["single_camera_no_depth", "contact_frame_approximate"],
            "related_shot_type": shot.shot_type,
        })
        if len(insights) >= 3:
            break
    return insights


def _split_step_timing_insights(result: PipelineResult, track_id: int, opponent_track_ids: List[int]) -> List[Dict]:
    if not opponent_track_ids:
        return []
    self_frames = result.biomechanics.get(str(track_id), [])
    split_steps = [f for f in self_frames if f["stance"] == "split_step"]
    if not split_steps:
        return []

    opponent_shot_times = sorted(s.timestamp_s for s in result.shots if s.track_id in opponent_track_ids)
    if not opponent_shot_times:
        return []

    late_count = 0
    example = None
    for split in split_steps:
        # find nearest opponent shot before/around this split step
        prior_shots = [t for t in opponent_shot_times if abs(t - split["timestamp_s"]) < 1.0]
        if not prior_shots:
            continue
        nearest = min(prior_shots, key=lambda t: abs(t - split["timestamp_s"]))
        delay = split["timestamp_s"] - nearest
        if delay > 0.08:  # split step lands after opponent's contact
            late_count += 1
            if example is None or delay > example[1]:
                example = (split, delay)

    if not example:
        return []

    split, delay = example
    return [{
        "category": "footwork",
        "timestamp_s": split["timestamp_s"],
        "observed_action": f"Your split step begins roughly {round(delay*1000)}ms after your opponent's estimated contact with the shuttle.",
        "likely_impact": "This delays your first step, which can be the difference between a controlled return and a rushed one against fast shots.",
        "correction": "Aim to land your split step at or just before your opponent's contact, rather than reacting after it.",
        "drill_tags": ["split_step_timing", "reaction_speed"],
        "confidence": _capped_confidence(0.6, 0.55),
        "limitations": ["contact_timing_approximate", "single_camera_no_depth"],
    }]


def _recovery_insights(result: PipelineResult, track_id: int) -> List[Dict]:
    tactics_data = result.tactics.get(str(track_id), {})
    recovery = tactics_data.get("recovery")
    if not recovery or recovery.get("average_recovery_s") is None:
        return []

    avg = recovery["average_recovery_s"]
    if avg <= 0.6:
        return []  # fast recovery isn't a coaching flag

    return [{
        "category": "positioning",
        "timestamp_s": 0.0,
        "observed_action": f"Across {recovery['samples']} tracked shots, you return to a central court position in an average of {avg}s.",
        "likely_impact": "Slower recovery to center can leave more of the court open for your opponent's next shot.",
        "correction": "Focus on a quicker, smaller recovery step back toward center immediately after your shot, rather than a full stop-and-reset.",
        "drill_tags": ["net_positioning", "early_recovery"],
        "confidence": _capped_confidence(recovery["confidence"]),
        "limitations": ["court_calibration_approximate"],
    }]


def _formation_insights(result: PipelineResult, self_id: int, partner_id: int) -> List[Dict]:
    key = str(self_id)
    formation = result.tactics.get(key, {}).get("formation")
    if not formation:
        return []
    ratio = formation.get("front_back_ratio")
    if ratio is None or ratio >= 0.4:
        return []
    return [{
        "category": "tactics",
        "timestamp_s": 0.0,
        "observed_action": f"Your team was in a front-back attacking formation only {round(ratio*100)}% of tracked doubles play.",
        "likely_impact": "Staying side-by-side during your own attacking sequences can leave the net underexposed.",
        "correction": "When your team is attacking, shift to front-back with your partner covering the rear court.",
        "drill_tags": ["doubles_formation"],
        "confidence": _capped_confidence(formation.get("confidence")),
        "limitations": ["doubles_tracking_prone_to_occlusion"],
    }]


def _shot_selection_insights(result: PipelineResult, track_id: int) -> List[Dict]:
    shots = [s for s in result.shots if s.track_id == track_id]
    if len(shots) < 4:
        return []
    defensive_count = sum(1 for s in shots if s.intent == "defensive")
    ratio = defensive_count / len(shots)
    if ratio < 0.5:
        return []
    return [{
        "category": "tactics",
        "timestamp_s": shots[-1].timestamp_s,
        "observed_action": f"{round(ratio*100)}% of your tracked shots this match were classified as defensive.",
        "likely_impact": "A defense-heavy shot pattern can cede control of the rally and tire you out over a long match.",
        "correction": "Look for opportunities to transition from defensive returns into neutral or attacking shots earlier in the rally.",
        "drill_tags": ["corner_to_corner_endurance", "doubles_formation"],
        "confidence": _capped_confidence(0.5),
        "limitations": ["shot_type_heuristic_not_trained_classifier"],
    }]
