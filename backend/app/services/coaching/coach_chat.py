"""Conversational coach (V2): intent-routed retrieval + templates over the
player's own stored data. Deterministic and auditable — every number in an
answer comes from the player's DB rows, so the coach cannot hallucinate
stats. See docs/V2_DESIGN.md §17 for the design rationale and the LLM
upgrade path.

Every answer ends with scope framing where relevant, and evidence entries
carry video ids + timestamps so the UI can deep-link to the moment.
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.video import Video, TrackedPerson
from app.models.analysis import Shot, CoachingInsight, MatchAnalytics
from app.models.coaching_content import Drill
from app.models.profile import PlayerProfile, ProfileHistorySnapshot

DISCLAIMER = "I coach from your video data — for hands-on technique work or anything injury-related, an in-person coach or physio is the right call."

SUGGESTED_QUESTIONS = [
    "Why am I losing points at the net?",
    "What should I train before my next tournament?",
    "Which shot should I use more often?",
    "Why do I lose balance after lunging?",
    "How is my progress trending?",
    "What's my weakest footwork pattern?",
]

# Checked BEFORE every other intent. A question mentioning pain or injury must
# never be answered as a technique question, even though it usually also
# contains technique words ("sharp pain when I lunge" also matches "balance").
MEDICAL_KEYWORDS = [
    "pain", "painful", "hurts", "hurting", "injur", "injury", "injured",
    "sprain", "strain", "tear", "torn", "swollen", "swelling", "ache", "aching",
    "tendon", "tendinitis", "tendonitis", "acl", "meniscus", "fracture",
    "diagnos", "physio", "physiotherap", "doctor", "medical", "concussion",
    "dizzy", "numb", "inflamed", "shin splint", "rehab",
]

MEDICAL_RESPONSE = (
    "That sounds like something to get looked at rather than coached through. "
    "I analyse video — I can't examine you, and I won't try to diagnose what's "
    "causing it. Please stop playing on it and see a physiotherapist, sports "
    "doctor, or another qualified medical professional, especially if the pain "
    "is sharp, swelling, or getting worse.\n\n"
    "Once a professional has cleared you, come back and I'll happily look at "
    "the movement patterns in your footage — landing mechanics and recovery "
    "position are things I can comment on from video."
)


INTENTS = [
    ("net", ["net", "front court", "forecourt", "kill"]),
    ("footwork", ["footwork", "split step", "split-step", "moving", "movement pattern", "slow to"]),
    ("balance", ["balance", "lunge", "lunging", "falling", "stable", "stability"]),
    ("training", ["train", "tournament", "practice", "prepare", "plan", "drill"]),
    ("shot_selection", ["which shot", "shot selection", "use more", "shot should", "variety", "predictable"]),
    ("smash", ["smash", "attack", "power"]),
    ("doubles", ["doubles", "partner", "rotate", "rotation", "formation"]),
    ("progress", ["progress", "improving", "better", "trend", "compare my last"]),
]


def answer_question(db: Session, user_id: str, question: str) -> Dict:
    q = question.lower()

    # Safety gate first: pain/injury questions are never routed to a coaching
    # handler, regardless of what else the question mentions.
    if any(k in q for k in MEDICAL_KEYWORDS):
        return {
            "answer": MEDICAL_RESPONSE,
            "evidence": [],
            "suggested_questions": ["What's my weakest footwork pattern?", "How is my progress trending?"],
            "confidence": None,
        }

    intent = None
    for name, keywords in INTENTS:
        if any(k in q for k in keywords):
            intent = name
            break

    ctx = _load_context(db, user_id)
    if not ctx["videos"]:
        return {
            "answer": "I don't have any analyzed matches from you yet — upload a match recording and I'll start building answers from your actual play.",
            "evidence": [], "suggested_questions": SUGGESTED_QUESTIONS[:3], "confidence": None,
        }

    handler = {
        "net": _answer_net, "footwork": _answer_footwork, "balance": _answer_balance,
        "training": _answer_training, "shot_selection": _answer_shot_selection,
        "smash": _answer_smash, "doubles": _answer_doubles, "progress": _answer_progress,
    }.get(intent)

    if handler is None:
        return _answer_fallback(ctx)
    return handler(db, ctx)


def _load_context(db: Session, user_id: str) -> Dict:
    videos = (
        db.query(Video).filter_by(owner_user_id=user_id, status="analyzed")
        .order_by(Video.created_at).all()
    )
    profile = db.query(PlayerProfile).filter_by(user_id=user_id).first()
    return {"user_id": user_id, "videos": videos, "profile": profile}


def _latest_video(ctx: Dict) -> Optional[Video]:
    return ctx["videos"][-1] if ctx["videos"] else None


def _self_shots(db: Session, video: Video) -> List[Shot]:
    self_tp = db.query(TrackedPerson).filter_by(video_id=video.id, role="self").first()
    if not self_tp:
        return []
    return db.query(Shot).filter_by(video_id=video.id, tracked_person_id=self_tp.id).all()


def _insights_by_category(db: Session, ctx: Dict, categories: List[str]) -> List[CoachingInsight]:
    video_ids = [v.id for v in ctx["videos"]]
    if not video_ids:
        return []
    rows = db.query(CoachingInsight).filter(CoachingInsight.video_id.in_(video_ids)).all()
    return [r for r in rows if r.category in categories]


def _drill_names(db: Session, tags: List[str], limit: int = 2) -> List[str]:
    names = []
    for d in db.query(Drill).all():
        if any(t in (d.target_issue_tags or []) for t in tags):
            names.append(d.name)
        if len(names) >= limit:
            break
    return names


def _evidence(insight: CoachingInsight) -> Dict:
    return {"video_id": insight.video_id, "timestamp_s": insight.timestamp_s, "label": insight.category}


def _answer_net(db: Session, ctx: Dict) -> Dict:
    video = _latest_video(ctx)
    shots = _self_shots(db, video)
    net_shots = [s for s in shots if s.shot_type in ("net_shot", "net_kill", "push")]
    positioning = _insights_by_category(db, ctx, ["positioning"])
    balance = _insights_by_category(db, ctx, ["technique"])

    parts = []
    evidence = []
    if net_shots:
        avg_conf = sum(s.confidence for s in net_shots) / len(net_shots)
        parts.append(
            f"In your latest match I tracked {len(net_shots)} net-area shots (classification confidence ~{round(avg_conf * 100)}%)."
        )
    lunge_insights = [i for i in balance if "lunge" in i.observed_action.lower() or "stability" in i.observed_action.lower() or "center of mass" in i.observed_action.lower()]
    if lunge_insights:
        top = lunge_insights[0]
        parts.append(f"The most likely culprit I can see: {top.observed_action[0].lower() + top.observed_action[1:]} That usually costs control on tight net shots.")
        evidence.append(_evidence(top))
    if positioning:
        top = positioning[0]
        parts.append(f"Positioning also plays a part — {top.observed_action[0].lower() + top.observed_action[1:]}")
        evidence.append(_evidence(top))
    if not parts:
        parts.append("I couldn't isolate a clear net-play issue from your tracked data yet — a match filmed from behind the baseline with the net visible would let me analyze this better.")

    drills = _drill_names(db, ["net_positioning", "lunge_stability"])
    if drills:
        parts.append(f"Worth drilling: {', '.join(drills)}.")

    return {"answer" : " ".join(parts), "evidence": evidence,
            "suggested_questions": ["Why do I lose balance after lunging?", "What should I train this week?"],
            "confidence": 0.5 if evidence else 0.25}


def _answer_footwork(db: Session, ctx: Dict) -> Dict:
    footwork = _insights_by_category(db, ctx, ["footwork", "positioning"])
    evidence = [_evidence(i) for i in footwork[:2]]
    if footwork:
        top = footwork[0]
        answer = (
            f"Your most consistent footwork finding: {top.observed_action} {top.likely_impact} "
            f"The fix to practice: {top.correction[0].lower() + top.correction[1:]} "
            f"(Confidence {round(top.confidence * 100)}% — single-camera timing estimates are approximate.)"
        )
    else:
        answer = "No specific footwork pattern stands out from your analyzed matches yet. More footage — especially at 60fps — sharpens split-step and recovery timing analysis."
    drills = _drill_names(db, ["split_step_timing", "lunge_stability"])
    if drills:
        answer += f" Recommended drills: {', '.join(drills)}."
    return {"answer": answer, "evidence": evidence,
            "suggested_questions": ["Why do I lose balance after lunging?", "How is my progress trending?"],
            "confidence": footwork[0].confidence if footwork else 0.25}


def _answer_balance(db: Session, ctx: Dict) -> Dict:
    technique = _insights_by_category(db, ctx, ["technique"])
    balance_insights = [i for i in technique if "balance" in i.observed_action.lower() or "center of mass" in i.observed_action.lower() or "lunge" in i.observed_action.lower()]
    evidence = [_evidence(i) for i in balance_insights[:2]]
    if balance_insights:
        top = balance_insights[0]
        answer = (
            f"Here's what your video shows: {top.observed_action} {top.likely_impact} "
            f"{top.correction} This is a video-based balance estimate, not a lab measurement — "
            f"but the pattern repeats enough to be worth training."
        )
    else:
        answer = ("Your tracked lunges didn't flag a clear balance problem. If it *feels* unstable, the usual suspects are lunge width "
                  "(front foot landing too narrow) and stepping before the split-step lands — both show up better on 60fps footage filmed from the baseline.")
    drills = _drill_names(db, ["lunge_stability", "balance_recovery"])
    if drills:
        answer += f" Try: {', '.join(drills)}."
    answer += f" {DISCLAIMER}"
    return {"answer": answer, "evidence": evidence,
            "suggested_questions": ["What's my weakest footwork pattern?", "What should I train this week?"],
            "confidence": balance_insights[0].confidence if balance_insights else 0.3}


def _answer_training(db: Session, ctx: Dict) -> Dict:
    profile = ctx["profile"]
    if not profile or not profile.training_plan:
        return {"answer": "Once you have an analyzed match, I'll build you a plan around your actual weaknesses.",
                "evidence": [], "suggested_questions": SUGGESTED_QUESTIONS[:2], "confidence": None}
    plan = profile.training_plan
    priorities = plan.get("priority_areas", [])
    weaknesses = ", ".join(profile.weaknesses) if profile.weaknesses else "general consistency"
    answer = (
        f"Based on {profile.matches_analyzed_count} analyzed match(es), your priority areas are: {', '.join(priorities) if priorities else weaknesses}. "
        f"{plan.get('weekly_theme', '')} "
    )
    tags = plan.get("recommended_drill_tags", [])
    drills = _drill_names(db, tags, limit=3)
    if drills:
        answer += f"This week's drills: {', '.join(drills)}. "
    answer += "Two focused sessions on these beat five unfocused ones — and upload your next match so I can check whether the work is transferring."
    return {"answer": answer, "evidence": [],
            "suggested_questions": ["Which shot should I use more often?", "How is my progress trending?"],
            "confidence": 0.6}


def _answer_shot_selection(db: Session, ctx: Dict) -> Dict:
    video = _latest_video(ctx)
    analytics_row = db.query(MatchAnalytics).filter_by(video_id=video.id).first()
    if not analytics_row:
        return _answer_fallback(ctx)
    blocks = analytics_row.analytics.get("blocks", {})
    mix = blocks.get("shot_mix", {})
    combos = blocks.get("shot_combinations", {})
    parts = []
    if mix.get("available"):
        top_types = list(mix["by_type"].items())[:2]
        under = [t for t in ("drop", "net_kill", "drive") if t not in mix["by_type"]]
        parts.append(
            "Your latest match leaned on " + " and ".join(f"{t} ({d['pct']}%)" for t, d in top_types) + "."
        )
        if under:
            parts.append(f"You rarely or never used: {', '.join(under)} — adding one of these from the same preparation makes you harder to read.")
    if combos.get("available") and combos.get("repeated_pairs"):
        top = combos["repeated_pairs"][0]
        parts.append(f"Also, your {top['pattern']} pattern repeated {top['count']} times — predictable patterns are the first thing good opponents exploit.")
    if not parts:
        parts.append("I don't have enough tracked shots yet to say — upload another match and I'll mine your patterns.")
    parts.append(f"(Shot labels are heuristic, ~{round((mix.get('confidence', 0.5)) * 100)}% confidence.)")
    return {"answer": " ".join(parts), "evidence": [],
            "suggested_questions": ["What should I train this week?", "How is my progress trending?"],
            "confidence": mix.get("confidence", 0.4)}


def _answer_smash(db: Session, ctx: Dict) -> Dict:
    videos = ctx["videos"]
    counts = []
    for v in videos[-2:]:
        shots = _self_shots(db, v)
        smashes = [s for s in shots if s.shot_type == "smash"]
        overhead_ok = sum(1 for s in smashes if s.contact_height == "overhead")
        counts.append((v, len(smashes), overhead_ok))
    if not counts or all(c[1] == 0 for c in counts):
        return {"answer": "I haven't tracked any clear smashes from you yet — they may be there, but the heuristic classifier only labels high-speed overhead swings it's confident about.",
                "evidence": [], "suggested_questions": ["Which shot should I use more often?"], "confidence": 0.3}
    parts = []
    if len(counts) == 2:
        (v1, n1, _), (v2, n2, _) = counts
        parts.append(f"Across your last two matches: {n1} tracked smashes in {v1.original_filename}, {n2} in {v2.original_filename}.")
    latest_v, n, ok = counts[-1]
    if n:
        parts.append(f"In the latest match, {ok} of {n} smashes had an approximate contact point above shoulder height — higher contact generally means steeper, safer smashes.")
    technique = _insights_by_category(db, ctx, ["technique"])
    contact_insights = [i for i in technique if "contact point" in i.observed_action.lower()]
    evidence = [_evidence(i) for i in contact_insights[:1]]
    if contact_insights:
        parts.append(f"One thing to check on video: {contact_insights[0].correction[0].lower() + contact_insights[0].correction[1:]}")
    return {"answer": " ".join(parts), "evidence": evidence,
            "suggested_questions": ["What should I train this week?"], "confidence": 0.45}


def _answer_doubles(db: Session, ctx: Dict) -> Dict:
    doubles_videos = [v for v in ctx["videos"] if v.match_format == "doubles"]
    if not doubles_videos:
        return {"answer": ("I haven't analyzed a doubles match from you yet. Once you upload one and tag your partner, "
                           "I can track your front-back vs side-by-side formation balance and rotation timing. The core principle meanwhile: "
                           "front-back when your team attacks, side-by-side when defending, and rotate as the shuttle's height changes who's attacking."),
                "evidence": [], "suggested_questions": ["What should I train this week?"], "confidence": None}
    tactics_insights = _insights_by_category(db, ctx, ["tactics"])
    formation = [i for i in tactics_insights if "formation" in i.observed_action.lower()]
    evidence = [_evidence(i) for i in formation[:1]]
    if formation:
        top = formation[0]
        answer = f"{top.observed_action} {top.likely_impact} {top.correction} (Confidence {round(top.confidence * 100)}% — doubles tracking through occlusion is approximate.)"
    else:
        answer = "Your doubles formations looked reasonable in the tracked spans — no repeated rotation failure stood out above my confidence threshold."
    drills = _drill_names(db, ["doubles_formation"])
    if drills:
        answer += f" Partner drill to sharpen it: {', '.join(drills)}."
    return {"answer": answer, "evidence": evidence,
            "suggested_questions": ["What's my weakest footwork pattern?"], "confidence": formation[0].confidence if formation else 0.35}


def _answer_progress(db: Session, ctx: Dict) -> Dict:
    snapshots = (
        db.query(ProfileHistorySnapshot).filter_by(user_id=ctx["user_id"])
        .order_by(ProfileHistorySnapshot.snapshot_at).all()
    )
    if len(snapshots) < 2:
        return {"answer": "I need at least two analyzed matches to show a trend. Upload another and I'll compare them.",
                "evidence": [], "suggested_questions": ["What should I train this week?"], "confidence": None}

    def avg(snap):
        vals = [v["score"] for v in snap.radar_scores.values() if v.get("score") is not None]
        return sum(vals) / len(vals) if vals else 0

    first_avg, last_avg = avg(snapshots[0]), avg(snapshots[-1])
    delta = last_avg - first_avg
    first, last = snapshots[0].radar_scores, snapshots[-1].radar_scores
    moves = []
    for dim in last:
        a, b = first.get(dim, {}).get("score"), last.get(dim, {}).get("score")
        if a is not None and b is not None:
            moves.append((dim.replace("_", " "), b - a))
    moves.sort(key=lambda m: m[1], reverse=True)
    up = [m for m in moves if m[1] > 2][:2]
    down = [m for m in moves if m[1] < -2][:1]
    parts = [f"Across {len(snapshots)} analyzed sessions your average attribute score moved {'+' if delta >= 0 else ''}{round(delta, 1)} points."]
    if up:
        parts.append("Biggest gains: " + ", ".join(f"{d} (+{round(v)})" for d, v in up) + ".")
    if down:
        parts.append("Watch: " + ", ".join(f"{d} ({round(v)})" for d, v in down) + ".")
    parts.append("These are video-derived estimates, so read the direction more than the exact numbers — the trend firms up with every upload.")
    return {"answer": " ".join(parts), "evidence": [],
            "suggested_questions": ["What should I train this week?", "Which shot should I use more often?"],
            "confidence": 0.5}


def _answer_fallback(ctx: Dict) -> Dict:
    profile = ctx["profile"]
    focus = None
    if profile and profile.weaknesses:
        focus = profile.weaknesses[0]
    answer = "I can answer questions about your net play, footwork, balance, smash, shot selection, doubles rotation, training plan, and progress."
    if focus:
        answer += f" If you want a starting point: your current biggest opportunity is {focus} — ask me \"what should I train this week?\""
    return {"answer": answer, "evidence": [], "suggested_questions": SUGGESTED_QUESTIONS[:4], "confidence": None}
