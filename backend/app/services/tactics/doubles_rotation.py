"""Advanced doubles rotation analysis (Phase 3).

Works entirely from the two teammates' court-mapped positions plus the shot
stream, so its accuracy is bounded by tracking + calibration quality — every
block carries a confidence capped by those inputs and a `basis` note.

Doubles tracking is the most occlusion-prone scenario the classical tracker
faces (four players, frequent crossing), so all outputs here should be read
as tendencies across the match, not per-rally verdicts. Interception-
opportunity detection and communication-pattern inference remain experimental
and are NOT emitted as claims (see docs/V2_DESIGN.md §18).
"""
from typing import Dict, List, Optional

FRONT_BACK_DEPTH_DOMINANCE = 1.2  # partners' depth gap must exceed width gap by this factor
WIDE_GAP_M = 3.4                  # partner spacing beyond this = a coverage gap on one side
OVERLAP_M = 1.2                   # partners closer than this = covering the same space


def _paired_positions(self_positions: List[Dict], partner_positions: List[Dict], tolerance_s: float = 0.15) -> List[Dict]:
    """Aligns the two players' position streams by timestamp."""
    pairs = []
    j = 0
    partner_sorted = sorted(partner_positions, key=lambda p: p["timestamp_s"])
    for sp in sorted(self_positions, key=lambda p: p["timestamp_s"]):
        while j < len(partner_sorted) - 1 and partner_sorted[j]["timestamp_s"] < sp["timestamp_s"] - tolerance_s:
            j += 1
        pp = partner_sorted[j] if j < len(partner_sorted) else None
        if pp and abs(pp["timestamp_s"] - sp["timestamp_s"]) <= tolerance_s:
            pairs.append({"t": sp["timestamp_s"], "self": sp, "partner": pp})
    return pairs


def _formation(pair: Dict) -> str:
    depth_gap = abs(pair["self"]["y"] - pair["partner"]["y"])
    width_gap = abs(pair["self"]["x"] - pair["partner"]["x"])
    return "front_back" if depth_gap > width_gap * FRONT_BACK_DEPTH_DOMINANCE else "side_by_side"


def analyze_doubles_rotation(
    self_positions: List[Dict],
    partner_positions: List[Dict],
    shots: List[Dict],           # [{timestamp_s, intent, is_self_team}] — team shots
    calibration_confidence: float,
    track_confidence: float,
) -> Dict:
    pairs = _paired_positions(self_positions, partner_positions)
    if len(pairs) < 20:
        return {
            "available": False, "confidence": 0.0,
            "basis": "Not enough overlapping tracked positions for you and your partner (occlusion or short tracks).",
        }

    base_conf = round(min(0.6, calibration_confidence * 0.7 + track_confidence * 0.3), 2)

    # Formation timeline + transition (rotation) events
    formations = [(p["t"], _formation(p)) for p in pairs]
    front_back_time = sum(1 for _, f in formations if f == "front_back") / len(formations)
    transitions = []
    for (t_prev, f_prev), (t_cur, f_cur) in zip(formations, formations[1:]):
        if f_prev != f_cur:
            transitions.append({"t": round(t_cur, 2), "to": f_cur})

    # Rotation timing after the team turns to attack: how long from an
    # offensive team shot (while side-by-side) until front-back is reached.
    rotation_delays = []
    missed_rotations = 0
    team_attacks = [s for s in shots if s.get("is_self_team") and s.get("intent") == "offensive"]
    for shot in team_attacks:
        at = shot["timestamp_s"]
        current = next((f for t, f in reversed(formations) if t <= at), None)
        if current != "side_by_side":
            continue
        reached = next((t for t, f in formations if t > at and f == "front_back" and t - at <= 4.0), None)
        if reached is not None:
            rotation_delays.append(reached - at)
        else:
            missed_rotations += 1

    avg_rotation_delay = round(sum(rotation_delays) / len(rotation_delays), 2) if rotation_delays else None
    attacks_from_side_by_side = len(rotation_delays) + missed_rotations

    # Partner spacing: overlap (stacked on the same space) and wide gaps
    distances = [
        ((p["self"]["x"] - p["partner"]["x"]) ** 2 + (p["self"]["y"] - p["partner"]["y"]) ** 2) ** 0.5
        for p in pairs
    ]
    overlap_ratio = sum(1 for d in distances if d < OVERLAP_M) / len(distances)
    wide_gap_ratio = sum(1 for d in distances if d > WIDE_GAP_M) / len(distances)

    # Open-middle channel during defense: side-by-side but with a wide lateral
    # gap between the partners (classic drive-exchange vulnerability).
    open_middle = 0
    side_by_side_count = 0
    for p, (_, f) in zip(pairs, formations):
        if f != "side_by_side":
            continue
        side_by_side_count += 1
        if abs(p["self"]["x"] - p["partner"]["x"]) > WIDE_GAP_M:
            open_middle += 1
    open_middle_ratio = round(open_middle / side_by_side_count, 2) if side_by_side_count else None

    findings = []
    if attacks_from_side_by_side >= 3 and missed_rotations / attacks_from_side_by_side >= 0.4:
        findings.append({
            "finding": f"On {missed_rotations} of {attacks_from_side_by_side} attacking sequences that began side-by-side, your pair had not shifted to front-back within 4 seconds.",
            "suggestion": "Agree on a trigger: whoever plays the attacking shot from the rear stays back; the other claims the net immediately.",
        })
    if avg_rotation_delay is not None and avg_rotation_delay > 1.5:
        findings.append({
            "finding": f"When your pair did rotate into attack, it took ~{avg_rotation_delay}s on average.",
            "suggestion": "Practice rotating on the shot cue rather than after watching the reply.",
        })
    if overlap_ratio > 0.2:
        findings.append({
            "finding": f"You and your partner were within {OVERLAP_M}m of each other for {round(overlap_ratio * 100)}% of tracked time — covering the same space.",
            "suggestion": "Define lanes: in side-by-side each player owns a half; in front-back the rear player covers everything behind the service line.",
        })
    if open_middle_ratio is not None and open_middle_ratio > 0.3:
        findings.append({
            "finding": f"During defensive (side-by-side) phases, a wide middle channel was open {round(open_middle_ratio * 100)}% of the time.",
            "suggestion": "Tighten toward the center line in defense — the middle is the fastest attacking route through a doubles pair.",
        })

    return {
        "available": True,
        "formation_split": {
            "front_back_pct": round(front_back_time * 100),
            "side_by_side_pct": round((1 - front_back_time) * 100),
        },
        "rotation": {
            "transitions_tracked": len(transitions),
            "avg_rotation_delay_s": avg_rotation_delay,
            "attacks_started_side_by_side": attacks_from_side_by_side,
            "missed_rotations": missed_rotations,
        },
        "spacing": {
            "overlap_pct": round(overlap_ratio * 100),
            "wide_gap_pct": round(wide_gap_ratio * 100),
            "open_middle_in_defense_pct": round(open_middle_ratio * 100) if open_middle_ratio is not None else None,
        },
        "findings": findings,
        "confidence": base_conf,
        "basis": (
            "Court-mapped positions of you and your partner aligned in time, plus team shot intents. "
            "Doubles tracking is occlusion-prone — read these as match-level tendencies, not per-rally verdicts."
        ),
    }
