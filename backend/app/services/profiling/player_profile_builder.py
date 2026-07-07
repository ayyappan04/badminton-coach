"""Builds/updates the longitudinal player profile from per-match summaries.

Radar scores are 0-100 heuristic composites derived from the CV pipeline's
shot, stability, and positioning signals aggregated across all of a player's
analyzed matches — not a validated performance metric, just a directionally
useful summary that improves as more matches are analyzed.
"""
from typing import Dict, List, Optional

RADAR_DIMENSIONS = [
    "attack", "control", "endurance", "defense", "mobility",
    "net_play", "power", "consistency", "tactical_awareness",
]


def _safe_ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def summarize_match(shot_type_counts: Dict[str, int], intent_counts: Dict[str, int],
                    avg_stability: Optional[float], avg_recovery_s: Optional[float],
                    rally_count: int, formation_front_back_ratio: Optional[float],
                    confidence: float) -> Dict:
    total_shots = sum(shot_type_counts.values()) or 1
    return {
        "shot_type_counts": shot_type_counts,
        "intent_counts": intent_counts,
        "avg_stability": avg_stability,
        "avg_recovery_s": avg_recovery_s,
        "rally_count": rally_count,
        "formation_front_back_ratio": formation_front_back_ratio,
        "confidence": confidence,
        "smash_ratio": _safe_ratio(shot_type_counts.get("smash", 0), total_shots),
        "net_shot_ratio": _safe_ratio(shot_type_counts.get("net_shot", 0) + shot_type_counts.get("net_kill", 0), total_shots),
        "defensive_ratio": _safe_ratio(intent_counts.get("defensive", 0), total_shots),
        "offensive_ratio": _safe_ratio(intent_counts.get("offensive", 0), total_shots),
    }


def build_radar_scores(match_summaries: List[Dict]) -> Dict[str, Dict]:
    if not match_summaries:
        return {dim: {"score": None, "confidence": 0.0} for dim in RADAR_DIMENSIONS}

    n = len(match_summaries)
    avg_offensive = sum(m["offensive_ratio"] for m in match_summaries) / n
    avg_defensive = sum(m["defensive_ratio"] for m in match_summaries) / n
    avg_smash = sum(m["smash_ratio"] for m in match_summaries) / n
    avg_net = sum(m["net_shot_ratio"] for m in match_summaries) / n
    stabilities = [m["avg_stability"] for m in match_summaries if m["avg_stability"] is not None]
    avg_stability = sum(stabilities) / len(stabilities) if stabilities else None
    recoveries = [m["avg_recovery_s"] for m in match_summaries if m["avg_recovery_s"] is not None]
    avg_recovery = sum(recoveries) / len(recoveries) if recoveries else None
    avg_rally_count = sum(m["rally_count"] for m in match_summaries) / n
    avg_confidence = sum(m["confidence"] for m in match_summaries) / n

    def score(v: float) -> float:
        return round(max(0.0, min(100.0, v * 100)), 1)

    scores = {
        "attack": score(avg_offensive * 0.7 + avg_smash * 0.3),
        "control": score(1 - abs(avg_offensive - avg_defensive)),
        "endurance": score(min(1.0, avg_rally_count / 15)),
        "defense": score(avg_defensive),
        "mobility": score(avg_stability) if avg_stability is not None else None,
        "net_play": score(avg_net),
        "power": score(avg_smash),
        "consistency": score(avg_stability * 0.6 + (1 - avg_defensive) * 0.4) if avg_stability is not None else None,
        "tactical_awareness": score(1 - abs(0.33 - avg_net) - abs(0.33 - avg_smash)) if True else None,
    }

    confidence = round(min(0.85, avg_confidence * min(1.0, n / 3)), 2)  # more matches -> more confidence, capped
    return {dim: {"score": scores.get(dim), "confidence": confidence} for dim in RADAR_DIMENSIONS}


def classify_play_style(match_summaries: List[Dict]) -> List[Dict]:
    if not match_summaries:
        return []

    n = len(match_summaries)
    avg_offensive = sum(m["offensive_ratio"] for m in match_summaries) / n
    avg_defensive = sum(m["defensive_ratio"] for m in match_summaries) / n
    avg_smash = sum(m["smash_ratio"] for m in match_summaries) / n
    avg_net = sum(m["net_shot_ratio"] for m in match_summaries) / n
    avg_rally_count = sum(m["rally_count"] for m in match_summaries) / n
    base_confidence = round(min(0.75, 0.3 + 0.1 * n), 2)

    labels = []
    if avg_smash > 0.2 and avg_offensive > 0.4:
        labels.append({
            "label": "Attacking",
            "evidence": f"Smashes make up {round(avg_smash*100)}% of tracked shots and {round(avg_offensive*100)}% of shots overall were classified offensive, averaged across {n} match(es).",
            "confidence": base_confidence,
        })
    if avg_defensive > 0.45:
        labels.append({
            "label": "Defensive counterattacker",
            "evidence": f"{round(avg_defensive*100)}% of tracked shots were classified defensive, averaged across {n} match(es).",
            "confidence": base_confidence,
        })
    if avg_net > 0.25:
        labels.append({
            "label": "Net-focused player",
            "evidence": f"Net shots and net kills make up {round(avg_net*100)}% of tracked shots, averaged across {n} match(es).",
            "confidence": base_confidence,
        })
    if avg_rally_count > 12:
        labels.append({
            "label": "Rally endurance player",
            "evidence": f"Average of {round(avg_rally_count,1)} rallies detected per match, suggesting a willingness to extend points.",
            "confidence": base_confidence * 0.9,
        })
    if not labels:
        labels.append({
            "label": "Balanced all-rounder",
            "evidence": "No single tendency (attack, defense, or net play) stood out strongly enough yet to dominate the profile — this may become clearer with more matches.",
            "confidence": round(base_confidence * 0.7, 2),
        })

    return labels


def derive_strengths_and_weaknesses(radar_scores: Dict[str, Dict]) -> Dict[str, List[str]]:
    scored = [(dim, v["score"]) for dim, v in radar_scores.items() if v["score"] is not None]
    if not scored:
        return {"strengths": [], "weaknesses": []}
    scored.sort(key=lambda x: x[1], reverse=True)
    strengths = [dim.replace("_", " ") for dim, s in scored[:2] if s >= 55]
    weaknesses = [dim.replace("_", " ") for dim, s in scored[-2:] if s < 55]
    return {"strengths": strengths, "weaknesses": weaknesses}


def build_training_plan(weaknesses: List[str], play_style_labels: List[Dict]) -> Dict:
    priority_map = {
        "net play": ["net_positioning", "lunge_stability"],
        "mobility": ["lunge_stability", "split_step_timing"],
        "power": ["smash_landing", "overhead_technique"],
        "defense": ["drive_recovery", "reaction_speed"],
        "consistency": ["overhead_technique", "reaction_speed"],
        "tactical awareness": ["doubles_formation"],
        "endurance": ["stamina", "movement_consistency"],
        "attack": ["overhead_technique", "smash_landing"],
        "control": ["net_positioning", "doubles_formation"],
    }
    priorities = weaknesses[:3] if weaknesses else ["consistency"]
    tags = []
    for w in priorities:
        tags.extend(priority_map.get(w, []))

    return {
        "priority_areas": priorities,
        "recommended_drill_tags": list(dict.fromkeys(tags)),  # de-dup, preserve order
        "weekly_theme": f"This week: focus on {priorities[0]}" if priorities else "This week: general match play",
    }
