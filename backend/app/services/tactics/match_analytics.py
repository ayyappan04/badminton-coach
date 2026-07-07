"""Whole-match analytics and tactical pattern mining (V2).

Every block in the returned analytics dict carries:
- `confidence`: 0-1, capped by the confidence of the signals it derives from
- `basis`: a plain-language note about what the number was computed from

Honesty constraints baked in (see docs/V2_DESIGN.md §18):
- No winner/error outcomes are claimed — rally endings record who hit last.
- The momentum block is a rally-length/intensity *proxy*, labeled as such.
- The fatigue block is a movement-speed trend *indicator*, not a physiological claim.
- Cross-court vs. straight usage is NOT computed (needs shuttle tracking).
"""
from collections import Counter
from typing import Dict, List, Optional

FEATURE_VERSION = "2.0.0"


def compute_match_analytics(
    rallies: List[Dict],       # [{rally_index, start_s, end_s, phases}]
    shots: List[Dict],         # [{rally_index, timestamp_s, shot_type, intent, contact_height, confidence, is_self}]
    self_positions: List[Dict],  # [{timestamp_s, x, y}] court-meters, analyzed player
    opponent_heatmap: Optional[Dict],  # occupancy grid for main opponent, or None
    net_y: float,
    calibration_confidence: float,
) -> Dict:
    self_shots = [s for s in shots if s.get("is_self")]
    blocks: Dict[str, Dict] = {}

    blocks["rally_stats"] = _rally_stats(rallies, shots)
    blocks["serve_patterns"] = _serve_patterns(rallies, shots)
    blocks["shot_mix"] = _shot_mix(self_shots)
    blocks["shot_combinations"] = _shot_combinations(self_shots)
    blocks["court_dominance"] = _court_dominance(self_positions, net_y, calibration_confidence)
    blocks["fatigue_indicator"] = _fatigue_indicator(rallies, self_positions)
    blocks["momentum_proxy"] = _momentum_proxy(rallies)
    blocks["pressure_zones"] = _pressure_zones(opponent_heatmap)
    blocks["strategy_recommendations"] = _strategy_recommendations(blocks, self_shots)

    return {"feature_version": FEATURE_VERSION, "blocks": blocks}


def _rally_stats(rallies: List[Dict], shots: List[Dict]) -> Dict:
    if not rallies:
        return {"available": False, "confidence": 0.0, "basis": "No rallies were segmented."}
    durations = [r["end_s"] - r["start_s"] for r in rallies]
    shots_per_rally = Counter(s["rally_index"] for s in shots)
    counts = [shots_per_rally.get(r["rally_index"], 0) for r in rallies]
    return {
        "available": True,
        "rally_count": len(rallies),
        "avg_duration_s": round(sum(durations) / len(durations), 1),
        "max_duration_s": round(max(durations), 1),
        "avg_shots_per_rally": round(sum(counts) / len(counts), 1) if counts else 0,
        "max_shots_in_rally": max(counts) if counts else 0,
        "confidence": 0.6,
        "basis": "Motion-based rally segmentation and swing-detected shots.",
    }


def _serve_patterns(rallies: List[Dict], shots: List[Dict]) -> Dict:
    """First tracked shot of each rally, treated as the serve; second as the
    return. A heuristic — serves that the swing detector missed are absent."""
    serves, returns = [], []
    for r in rallies:
        rally_shots = sorted([s for s in shots if s["rally_index"] == r["rally_index"]], key=lambda s: s["timestamp_s"])
        if rally_shots:
            serves.append(rally_shots[0])
        if len(rally_shots) > 1:
            returns.append(rally_shots[1])

    def summarize(events):
        if not events:
            return None
        self_count = sum(1 for e in events if e.get("is_self"))
        types = Counter(e["shot_type"] for e in events if e.get("is_self"))
        return {
            "tracked": len(events),
            "by_self": self_count,
            "self_type_mix": dict(types.most_common(4)),
        }

    return {
        "available": bool(serves),
        "serves": summarize(serves),
        "returns": summarize(returns),
        "confidence": 0.45,
        "basis": "First and second swing events of each rally; serve type is inferred, not directly classified.",
    }


def _shot_mix(self_shots: List[Dict]) -> Dict:
    if not self_shots:
        return {"available": False, "confidence": 0.0, "basis": "No shots attributed to you were tracked."}
    types = Counter(s["shot_type"] for s in self_shots)
    intents = Counter(s["intent"] for s in self_shots)
    heights = Counter(s["contact_height"] for s in self_shots)
    total = len(self_shots)
    variety = len([t for t, c in types.items() if c >= 2])
    avg_conf = sum(s["confidence"] for s in self_shots) / total
    return {
        "available": True,
        "total_shots": total,
        "by_type": {k: {"count": v, "pct": round(v / total * 100)} for k, v in types.most_common()},
        "by_intent": {k: round(v / total * 100) for k, v in intents.items()},
        "by_contact_height": {k: round(v / total * 100) for k, v in heights.items()},
        "shot_variety": variety,
        "confidence": round(min(0.65, avg_conf), 2),
        "basis": "Heuristic shot classification from swing speed and contact height (Phase-2 trained classifier will improve this).",
    }


def _shot_combinations(self_shots: List[Dict]) -> Dict:
    """Repeated consecutive shot patterns (2- and 3-grams) within rallies —
    the 'predictability' signal."""
    if len(self_shots) < 4:
        return {"available": False, "confidence": 0.0, "basis": "Too few tracked shots for pattern mining."}

    by_rally: Dict[int, List[str]] = {}
    for s in sorted(self_shots, key=lambda s: s["timestamp_s"]):
        by_rally.setdefault(s["rally_index"], []).append(s["shot_type"])

    bigrams, trigrams = Counter(), Counter()
    for seq in by_rally.values():
        for a, b in zip(seq, seq[1:]):
            bigrams[f"{a} → {b}"] += 1
        for a, b, c in zip(seq, seq[1:], seq[2:]):
            trigrams[f"{a} → {b} → {c}"] += 1

    top_bigrams = [{"pattern": p, "count": c} for p, c in bigrams.most_common(3) if c >= 2]
    top_trigrams = [{"pattern": p, "count": c} for p, c in trigrams.most_common(2) if c >= 2]

    total_bigrams = sum(bigrams.values())
    predictability = None
    if top_bigrams and total_bigrams >= 6:
        predictability = round(top_bigrams[0]["count"] / total_bigrams, 2)

    return {
        "available": bool(top_bigrams),
        "repeated_pairs": top_bigrams,
        "repeated_triples": top_trigrams,
        "predictability_ratio": predictability,  # share of your most common transition
        "confidence": 0.5,
        "basis": "Consecutive shot-type sequences within rallies, from heuristic shot labels.",
    }


def _court_dominance(self_positions: List[Dict], net_y: float, calibration_confidence: float) -> Dict:
    if not self_positions:
        return {"available": False, "confidence": 0.0, "basis": "No court-mapped positions (calibration unavailable)."}
    # Determine which side of the net the player mostly occupies, then split
    # that half into front (near net) and rear (near baseline).
    ys = [p["y"] for p in self_positions]
    on_near_side = sum(1 for y in ys if y > net_y) >= len(ys) / 2
    if on_near_side:
        half = [y for y in ys if y > net_y]
        front = sum(1 for y in half if y < net_y + (max(half) - net_y) / 2) if half else 0
    else:
        half = [y for y in ys if y <= net_y]
        front = sum(1 for y in half if y > net_y - (net_y - min(half)) / 2) if half else 0
    total = len(half) if half else 1
    front_pct = round(front / total * 100)
    return {
        "available": True,
        "front_court_pct": front_pct,
        "rear_court_pct": 100 - front_pct,
        "confidence": round(min(0.7, calibration_confidence), 2),
        "basis": "Your tracked foot position mapped through the court calibration; approximate to the calibration's accuracy.",
    }


def _fatigue_indicator(rallies: List[Dict], self_positions: List[Dict]) -> Dict:
    """Linear trend of per-rally average movement speed across the match.
    A clearly negative slope MAY indicate fatigue — flagged as an indicator,
    never a physiological measurement."""
    if len(rallies) < 4 or len(self_positions) < 10:
        return {"available": False, "confidence": 0.0, "basis": "Not enough rallies/positions for a movement trend."}

    per_rally_speed = []
    for r in rallies:
        pts = [p for p in self_positions if r["start_s"] <= p["timestamp_s"] <= r["end_s"]]
        if len(pts) < 3:
            continue
        dist = 0.0
        for a, b in zip(pts, pts[1:]):
            dist += ((b["x"] - a["x"]) ** 2 + (b["y"] - a["y"]) ** 2) ** 0.5
        duration = pts[-1]["timestamp_s"] - pts[0]["timestamp_s"]
        if duration > 0:
            per_rally_speed.append(dist / duration)

    if len(per_rally_speed) < 4:
        return {"available": False, "confidence": 0.0, "basis": "Not enough rallies with continuous tracking."}

    n = len(per_rally_speed)
    mean_x = (n - 1) / 2
    mean_y = sum(per_rally_speed) / n
    cov = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(per_rally_speed))
    var = sum((i - mean_x) ** 2 for i in range(n))
    slope = cov / var if var else 0.0
    relative_slope = slope / mean_y if mean_y else 0.0

    return {
        "available": True,
        "movement_speed_trend": "declining" if relative_slope < -0.02 else ("rising" if relative_slope > 0.02 else "stable"),
        "relative_change_per_rally_pct": round(relative_slope * 100, 1),
        "rallies_measured": n,
        "confidence": 0.35,
        "basis": "Trend of average movement speed per rally. An indicator only — camera angle, rally style, and tactics also change movement speed.",
    }


def _momentum_proxy(rallies: List[Dict]) -> Dict:
    """Rolling rally-duration trend. Without score detection the system does
    not know who won points, so this is a rhythm/intensity proxy, not a
    scoreline momentum measure."""
    if len(rallies) < 5:
        return {"available": False, "confidence": 0.0, "basis": "Too few rallies for a trend."}
    durations = [r["end_s"] - r["start_s"] for r in rallies]
    window = max(3, len(durations) // 4)
    rolling = [round(sum(durations[max(0, i - window + 1):i + 1]) / len(durations[max(0, i - window + 1):i + 1]), 1) for i in range(len(durations))]
    return {
        "available": True,
        "rolling_avg_rally_duration_s": rolling,
        "confidence": 0.4,
        "basis": "Rolling average rally duration. A proxy for match rhythm — point outcomes are unknown without score tracking.",
    }


def _pressure_zones(opponent_heatmap: Optional[Dict]) -> Dict:
    if not opponent_heatmap or not opponent_heatmap.get("occupancy"):
        return {"available": False, "confidence": 0.0, "basis": "Opponent positions were not court-mapped."}
    grid = opponent_heatmap["occupancy"]
    rows, cols = len(grid), len(grid[0]) if grid else 0
    flat = [(grid[r][c], r, c) for r in range(rows) for c in range(cols)]
    flat.sort(reverse=True)
    hot = [{"row": r, "col": c, "occupancy": round(v, 3)} for v, r, c in flat[:3] if v > 0]
    return {
        "available": bool(hot),
        "opponent_hot_zones": hot,
        "grid": {"rows": rows, "cols": cols},
        "confidence": round(min(0.6, opponent_heatmap.get("confidence", 0.4)), 2),
        "basis": "Where your opponent spent the most time — zones they defend comfortably; the complement suggests space to attack.",
    }


def _strategy_recommendations(blocks: Dict, self_shots: List[Dict]) -> Dict:
    """Rule-based strategy suggestions derived from the computed blocks.
    Each recommendation cites its evidence block."""
    recs: List[Dict] = []

    combos = blocks.get("shot_combinations", {})
    if combos.get("available") and combos.get("predictability_ratio") and combos["predictability_ratio"] >= 0.3:
        top = combos["repeated_pairs"][0]
        recs.append({
            "recommendation": f"Your most common shot pattern ({top['pattern']}) makes up a large share of your transitions — mix in alternatives from the same preparation so opponents can't pre-move.",
            "evidence": f"Pattern occurred {top['count']} times; {round(combos['predictability_ratio'] * 100)}% of your tracked transitions.",
            "confidence": combos["confidence"],
        })

    mix = blocks.get("shot_mix", {})
    if mix.get("available"):
        defensive_pct = mix["by_intent"].get("defensive", 0)
        if defensive_pct >= 45:
            recs.append({
                "recommendation": "A large share of your shots are defensive — look for earlier opportunities to convert defense into neutral or attacking shots, especially off short lifts.",
                "evidence": f"{defensive_pct}% of your tracked shots were classified defensive.",
                "confidence": mix["confidence"],
            })
        if mix.get("shot_variety", 0) <= 3 and mix.get("total_shots", 0) >= 12:
            recs.append({
                "recommendation": "Your shot variety this match was narrow — adding even one more reliable option (e.g. a drop from your clear preparation) makes your game harder to read.",
                "evidence": f"Only {mix['shot_variety']} shot types were used more than once across {mix['total_shots']} tracked shots.",
                "confidence": mix["confidence"],
            })

    dominance = blocks.get("court_dominance", {})
    if dominance.get("available"):
        if dominance["rear_court_pct"] >= 70:
            recs.append({
                "recommendation": "You spent most of the match in the rear court — practice moving in behind your drops and clears to claim the net earlier.",
                "evidence": f"~{dominance['rear_court_pct']}% of tracked time in the rear half of your side.",
                "confidence": dominance["confidence"],
            })
        elif dominance["front_court_pct"] >= 70:
            recs.append({
                "recommendation": "You spent most of the match near the net — work on rear-court confidence so deep clears don't force weak replies.",
                "evidence": f"~{dominance['front_court_pct']}% of tracked time in the front half of your side.",
                "confidence": dominance["confidence"],
            })

    pressure = blocks.get("pressure_zones", {})
    if pressure.get("available") and pressure.get("opponent_hot_zones"):
        zone = pressure["opponent_hot_zones"][0]
        rows = pressure["grid"]["rows"]
        area = "rear court" if zone["row"] < rows / 3 or zone["row"] > 2 * rows / 3 else "mid court"
        recs.append({
            "recommendation": f"Your opponent camped in one zone ({area}) — target the diagonally opposite corner to stretch their coverage.",
            "evidence": "Opponent occupancy heatmap concentration.",
            "confidence": pressure["confidence"],
        })

    fatigue = blocks.get("fatigue_indicator", {})
    if fatigue.get("available") and fatigue.get("movement_speed_trend") == "declining":
        recs.append({
            "recommendation": "Your movement speed drifted down late in the match — consider longer-rally conditioning, and favor higher-percentage shots when tired instead of forcing winners.",
            "evidence": f"~{abs(fatigue['relative_change_per_rally_pct'])}% average speed change per rally across {fatigue['rallies_measured']} rallies (indicator only).",
            "confidence": fatigue["confidence"],
        })

    return {
        "available": bool(recs),
        "recommendations": recs,
        "confidence": round(min([r["confidence"] for r in recs], default=0.0), 2),
        "basis": "Rule-based synthesis of the analytics blocks above; each recommendation cites its evidence.",
    }
