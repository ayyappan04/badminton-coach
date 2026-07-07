"""Rally phase segmentation (V2): labels each rally's internal structure —
serve, return, attack / neutral / defense windows, and the rally-ending
event — from the ordered shot events within the rally.

Phases are from the analyzed player's perspective: "attack" means the
analyzed player's shots in that window were predominantly offensive.

Rally OUTCOMES (winner / forced error / unforced error / net / out) are
deliberately not claimed here: without shuttle-landing detection or score
reading, the pipeline cannot know who won the point. The ending event records
only who hit last and with what shot — see docs/V2_DESIGN.md §18.
"""
from typing import Dict, List, Optional

from app.services.cv_pipeline.types import RallySegment, ShotEvent

PHASE_WINDOW_SHOTS = 3


def analyze_rally_phases(
    rally: RallySegment,
    shots: List[ShotEvent],
    self_track_id: Optional[int],
) -> List[Dict]:
    """Returns [{phase, start_s, end_s, confidence}] covering the rally span."""
    rally_shots = sorted(
        [s for s in shots if s.rally_index == rally.rally_index],
        key=lambda s: s.timestamp_s,
    )

    if not rally_shots:
        return [{
            "phase": "neutral",
            "start_s": rally.start_timestamp_s,
            "end_s": rally.end_timestamp_s,
            "confidence": round(rally.confidence * 0.5, 2),
        }]

    phases: List[Dict] = []

    serve_end = rally_shots[0].timestamp_s + 0.2 if len(rally_shots) > 1 else rally.end_timestamp_s
    phases.append({
        "phase": "serve",
        "start_s": rally.start_timestamp_s,
        "end_s": min(serve_end, rally.end_timestamp_s),
        "confidence": round(min(rally_shots[0].confidence, 0.6), 2),
    })

    if len(rally_shots) > 1:
        return_end = rally_shots[1].timestamp_s + 0.2 if len(rally_shots) > 2 else rally.end_timestamp_s
        phases.append({
            "phase": "return",
            "start_s": phases[-1]["end_s"],
            "end_s": min(return_end, rally.end_timestamp_s),
            "confidence": round(min(rally_shots[1].confidence, 0.6), 2),
        })

    # Middle of the rally: sliding windows of shots, labeled by the analyzed
    # player's dominant intent within each window.
    mid_shots = rally_shots[2:-1] if len(rally_shots) > 3 else []
    if mid_shots:
        i = 0
        while i < len(mid_shots):
            window = mid_shots[i:i + PHASE_WINDOW_SHOTS]
            self_window = [s for s in window if self_track_id is not None and s.track_id == self_track_id]
            basis = self_window if self_window else window
            offensive = sum(1 for s in basis if s.intent == "offensive")
            defensive = sum(1 for s in basis if s.intent == "defensive")
            if offensive > defensive and offensive >= max(1, len(basis) // 2):
                phase = "attack"
            elif defensive > offensive and defensive >= max(1, len(basis) // 2):
                phase = "defense"
            else:
                phase = "neutral"
            start_s = max(phases[-1]["end_s"], window[0].timestamp_s - 0.1)
            end_s = min(window[-1].timestamp_s + 0.2, rally.end_timestamp_s)
            confidence = round(min([s.confidence for s in window] + [0.6]), 2)
            if end_s > start_s:
                phases.append({"phase": phase, "start_s": start_s, "end_s": end_s, "confidence": confidence})
            i += PHASE_WINDOW_SHOTS

    # Rally-ending event: the final tracked shot. Who hit it and with what,
    # but never a claimed outcome.
    last_shot = rally_shots[-1]
    if len(rally_shots) > 1:
        phases.append({
            "phase": "ending",
            "start_s": max(phases[-1]["end_s"], last_shot.timestamp_s - 0.2),
            "end_s": rally.end_timestamp_s,
            "confidence": round(min(last_shot.confidence, 0.6), 2),
        })

    # Close any gap between labeled phases and rally end
    if phases and phases[-1]["end_s"] < rally.end_timestamp_s - 0.01:
        phases[-1]["end_s"] = rally.end_timestamp_s

    return phases


def ending_event(rally: RallySegment, shots: List[ShotEvent], role_by_track: Dict[int, str]) -> Dict:
    rally_shots = sorted(
        [s for s in shots if s.rally_index == rally.rally_index],
        key=lambda s: s.timestamp_s,
    )
    if not rally_shots:
        return {"ending_shot_type": None, "ending_track_role": None}
    last = rally_shots[-1]
    return {
        "ending_shot_type": last.shot_type,
        "ending_track_role": role_by_track.get(last.track_id, "unassigned"),
    }
