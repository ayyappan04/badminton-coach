from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import or_, and_
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.video import Video
from app.models.community import Friendship, SharedClip, PracticePlan, Challenge, Club, ClubMembership

router = APIRouter(tags=["community"])


# ---- Friends ----

class FriendRequestCreate(BaseModel):
    to_user_id: str


@router.get("/friends")
def list_friends(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Friendship).filter(
        or_(Friendship.user_id_a == current_user.id, Friendship.user_id_b == current_user.id)
    ).all()
    result = []
    for r in rows:
        other_id = r.user_id_b if r.user_id_a == current_user.id else r.user_id_a
        other = db.get(User, other_id)
        if not other:
            continue
        result.append({
            "friendship_id": r.id, "user_id": other.id, "display_name": other.display_name,
            "status": r.status, "requested_by_me": r.user_id_a == current_user.id,
        })
    return result


@router.post("/friends/requests")
def create_friend_request(payload: FriendRequestCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if payload.to_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot friend yourself")
    target = db.get(User, payload.to_user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    existing = db.query(Friendship).filter(
        or_(
            and_(Friendship.user_id_a == current_user.id, Friendship.user_id_b == payload.to_user_id),
            and_(Friendship.user_id_a == payload.to_user_id, Friendship.user_id_b == current_user.id),
        )
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Friendship already exists or is pending")
    friendship = Friendship(user_id_a=current_user.id, user_id_b=payload.to_user_id, status="pending")
    db.add(friendship)
    db.commit()
    return {"friendship_id": friendship.id, "status": "pending"}


@router.post("/friends/requests/{friendship_id}/accept")
def accept_friend_request(friendship_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    friendship = db.get(Friendship, friendship_id)
    if not friendship or friendship.user_id_b != current_user.id:
        raise HTTPException(status_code=404, detail="Friend request not found")
    friendship.status = "accepted"
    db.commit()
    return {"status": "accepted"}


# ---- Shared clips ----

class SharedClipCreate(BaseModel):
    video_id: str
    clip_start_s: float
    clip_end_s: float
    visibility: str = "private"
    caption: Optional[str] = None


@router.post("/videos/{video_id}/clips")
def create_shared_clip(video_id: str, payload: SharedClipCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    clip = SharedClip(
        video_id=video_id, created_by_user_id=current_user.id,
        clip_start_s=payload.clip_start_s, clip_end_s=payload.clip_end_s,
        visibility=payload.visibility, caption=payload.caption,
    )
    db.add(clip)
    db.commit()
    return {"clip_id": clip.id}


@router.get("/clips/shared")
def list_shared_clips(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    friend_ids = set()
    for r in db.query(Friendship).filter(
        or_(Friendship.user_id_a == current_user.id, Friendship.user_id_b == current_user.id),
        Friendship.status == "accepted",
    ).all():
        friend_ids.add(r.user_id_b if r.user_id_a == current_user.id else r.user_id_a)

    clips = db.query(SharedClip).filter(
        or_(
            SharedClip.visibility == "public",
            and_(SharedClip.visibility == "friends", SharedClip.created_by_user_id.in_(friend_ids)) if friend_ids else False,
            SharedClip.created_by_user_id == current_user.id,
        )
    ).all()
    return [{
        "clip_id": c.id, "video_id": c.video_id, "created_by_user_id": c.created_by_user_id,
        "clip_start_s": c.clip_start_s, "clip_end_s": c.clip_end_s,
        "visibility": c.visibility, "caption": c.caption,
    } for c in clips]


# ---- Practice / match planning ----

class PracticePlanCreate(BaseModel):
    kind: str = "practice"
    participants: List[str] = []
    scheduled_at: datetime
    location: Optional[str] = None
    notes: Optional[str] = None
    linked_drill_ids: List[str] = []


@router.post("/practice-plans")
def create_practice_plan(payload: PracticePlanCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plan = PracticePlan(
        created_by_user_id=current_user.id, kind=payload.kind, participants=payload.participants,
        scheduled_at=payload.scheduled_at, location=payload.location, notes=payload.notes,
        linked_drill_ids=payload.linked_drill_ids,
    )
    db.add(plan)
    db.commit()
    return {"plan_id": plan.id}


@router.get("/practice-plans")
def list_practice_plans(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Plans I created plus group sessions where a friend added me as a
    participant (Phase 4 group training)."""
    own = db.query(PracticePlan).filter_by(created_by_user_id=current_user.id).all()
    own_ids = {p.id for p in own}
    invited = [
        p for p in db.query(PracticePlan).all()
        if p.id not in own_ids and current_user.id in (p.participants or [])
    ]
    plans = sorted(own + invited, key=lambda p: p.scheduled_at)
    names = {}
    return [{
        "plan_id": p.id, "kind": p.kind, "participants": p.participants,
        "scheduled_at": p.scheduled_at.isoformat(), "location": p.location,
        "notes": p.notes, "linked_drill_ids": p.linked_drill_ids,
        "created_by_me": p.created_by_user_id == current_user.id,
        "organizer_name": names.setdefault(
            p.created_by_user_id,
            (db.get(User, p.created_by_user_id).display_name if db.get(User, p.created_by_user_id) else "Unknown"),
        ),
    } for p in plans]


# ---- Clubs (V2) ----

class ClubCreate(BaseModel):
    name: str
    description: Optional[str] = None


@router.get("/community/clubs")
def list_clubs(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    memberships = {m.club_id: m.role for m in db.query(ClubMembership).filter_by(user_id=current_user.id).all()}
    clubs = db.query(Club).all()
    result = []
    for c in clubs:
        member_count = db.query(ClubMembership).filter_by(club_id=c.id).count()
        result.append({
            "club_id": c.id, "name": c.name, "description": c.description,
            "member_count": member_count, "my_role": memberships.get(c.id),
        })
    return result


@router.post("/community/clubs")
def create_club(payload: ClubCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    club = Club(name=payload.name, description=payload.description, owner_user_id=current_user.id)
    db.add(club)
    db.flush()
    db.add(ClubMembership(club_id=club.id, user_id=current_user.id, role="admin"))
    db.commit()
    return {"club_id": club.id}


@router.post("/community/clubs/{club_id}/join")
def join_club(club_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    club = db.get(Club, club_id)
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")
    existing = db.query(ClubMembership).filter_by(club_id=club_id, user_id=current_user.id).first()
    if existing:
        return {"joined": True, "role": existing.role}
    db.add(ClubMembership(club_id=club_id, user_id=current_user.id, role="member"))
    db.commit()
    return {"joined": True, "role": "member"}


@router.get("/community/clubs/{club_id}")
def club_detail(club_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Club members plus a team dashboard. Metrics appear ONLY for members who
    opted in via consent-settings (share_progress_with_club) — everyone else
    is listed by name and role with no performance data (Phase 3 per-metric
    sharing, docs/V2_DESIGN.md §9)."""
    from app.models.user import ConsentSettings
    from app.models.profile import PlayerProfile

    club = db.get(Club, club_id)
    if not club:
        raise HTTPException(status_code=404, detail="Club not found")
    memberships = db.query(ClubMembership).filter_by(club_id=club_id).all()
    if current_user.id not in {m.user_id for m in memberships}:
        raise HTTPException(status_code=403, detail="Club details are visible to members only")

    members = []
    shared_scores = []
    for m in memberships:
        member_user = db.get(User, m.user_id)
        if not member_user:
            continue
        entry = {"user_id": m.user_id, "display_name": member_user.display_name, "role": m.role, "shares_progress": False}
        consent = db.query(ConsentSettings).filter_by(user_id=m.user_id).first()
        if consent and consent.share_progress_with_club:
            profile = db.query(PlayerProfile).filter_by(user_id=m.user_id).first()
            if profile and profile.radar_scores:
                scores = [v["score"] for v in profile.radar_scores.values() if isinstance(v, dict) and v.get("score") is not None]
                dev_score = round(sum(scores) / len(scores), 1) if scores else None
                entry.update({
                    "shares_progress": True,
                    "development_score": dev_score,
                    "matches_analyzed": profile.matches_analyzed_count,
                    "top_style": (profile.play_style_labels or [{}])[0].get("label"),
                })
                if dev_score is not None:
                    shared_scores.append(dev_score)
        members.append(entry)

    return {
        "club_id": club.id, "name": club.name, "description": club.description,
        "members": members,
        "team_dashboard": {
            "sharing_members": len(shared_scores),
            "avg_development_score": round(sum(shared_scores) / len(shared_scores), 1) if shared_scores else None,
            "note": "Shows only members who opted in to share progress with this club.",
        },
    }


# ---- Training streak (V2) ----

@router.get("/community/streak")
def training_streak(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Consecutive calendar weeks (ending this week) with at least one uploaded
    match or scheduled practice — a light consistency nudge, not a gamified score."""
    from datetime import datetime, timezone, timedelta

    activity_dates = [v.created_at for v in db.query(Video).filter_by(owner_user_id=current_user.id).all()]
    activity_dates += [p.scheduled_at for p in db.query(PracticePlan).filter_by(created_by_user_id=current_user.id).all()]
    if not activity_dates:
        return {"streak_weeks": 0}

    def week_key(dt):
        iso = dt.isocalendar()
        return (iso[0], iso[1])

    weeks = {week_key(d) for d in activity_dates if d is not None}
    streak = 0
    cursor = datetime.now(timezone.utc)
    while week_key(cursor) in weeks:
        streak += 1
        cursor -= timedelta(weeks=1)
    return {"streak_weeks": streak}


# ---- Challenges ----

class ChallengeCreate(BaseModel):
    opponent_user_id: str
    description: Optional[str] = None


@router.post("/challenges")
def create_challenge(payload: ChallengeCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    challenge = Challenge(
        created_by_user_id=current_user.id, opponent_user_id=payload.opponent_user_id,
        description=payload.description, status="pending",
    )
    db.add(challenge)
    db.commit()
    return {"challenge_id": challenge.id}


@router.get("/challenges")
def list_challenges(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Challenge).filter(
        or_(Challenge.created_by_user_id == current_user.id, Challenge.opponent_user_id == current_user.id)
    ).order_by(Challenge.created_at.desc()).all()
    names = {}

    def name_of(uid):
        if uid not in names:
            u = db.get(User, uid)
            names[uid] = u.display_name if u else "Unknown"
        return names[uid]

    return [{
        "challenge_id": c.id, "created_by_user_id": c.created_by_user_id,
        "opponent_user_id": c.opponent_user_id, "description": c.description,
        "status": c.status, "result": c.result,
        "challenger_name": name_of(c.created_by_user_id),
        "opponent_name": name_of(c.opponent_user_id),
        "i_am_opponent": c.opponent_user_id == current_user.id,
    } for c in rows]


@router.post("/challenges/{challenge_id}/accept")
def accept_challenge(challenge_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.get(Challenge, challenge_id)
    if not c or c.opponent_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Challenge not found")
    if c.status != "pending":
        raise HTTPException(status_code=400, detail=f"Challenge is already {c.status}")
    c.status = "accepted"
    db.commit()
    return {"status": "accepted"}


class ChallengeComplete(BaseModel):
    result: str  # free-text, e.g. "Arun won 21-18"


@router.post("/challenges/{challenge_id}/complete")
def complete_challenge(challenge_id: str, payload: ChallengeComplete,
                       current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    c = db.get(Challenge, challenge_id)
    if not c or current_user.id not in (c.created_by_user_id, c.opponent_user_id):
        raise HTTPException(status_code=404, detail="Challenge not found")
    if c.status != "accepted":
        raise HTTPException(status_code=400, detail="Only accepted challenges can be completed")
    c.status = "completed"
    c.result = payload.result
    db.commit()
    return {"status": "completed", "result": c.result}


# ---- Shared progress milestones (Phase 4) ----

@router.get("/community/milestones")
def milestones(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Recent progress milestones for me and — where their profile share scope
    allows — my accepted friends. Milestones are derived facts (match counts,
    streaks, first doubles match), never raw analysis data."""
    from app.models.user import ConsentSettings
    from app.models.profile import PlayerProfile

    friend_ids = set()
    for r in db.query(Friendship).filter(
        or_(Friendship.user_id_a == current_user.id, Friendship.user_id_b == current_user.id),
        Friendship.status == "accepted",
    ).all():
        friend_ids.add(r.user_id_b if r.user_id_a == current_user.id else r.user_id_a)

    def milestones_for(user_id: str, name: str, is_self: bool):
        found = []
        profile = db.query(PlayerProfile).filter_by(user_id=user_id).first()
        count = profile.matches_analyzed_count if profile else 0
        for threshold in (1, 5, 10, 25, 50):
            if count >= threshold:
                found.append({"who": "You" if is_self else name, "milestone": f"{threshold} match{'es' if threshold > 1 else ''} analyzed", "kind": "matches"})
        if db.query(Video).filter_by(owner_user_id=user_id, match_format="doubles", status="analyzed").count() > 0:
            found.append({"who": "You" if is_self else name, "milestone": "First doubles match analyzed", "kind": "doubles"})
        if profile and profile.radar_scores:
            scores = [v["score"] for v in profile.radar_scores.values() if isinstance(v, dict) and v.get("score") is not None]
            if scores and sum(scores) / len(scores) >= 50:
                found.append({"who": "You" if is_self else name, "milestone": "Development score reached 50", "kind": "score"})
        return found[-3:]  # most significant few, not an endless list

    result = milestones_for(current_user.id, "You", True)
    for fid in friend_ids:
        consent = db.query(ConsentSettings).filter_by(user_id=fid).first()
        scope = consent.default_profile_share_scope if consent else "private"
        if scope in ("friends", "public"):
            friend = db.get(User, fid)
            if friend:
                result.extend(milestones_for(fid, friend.display_name, False))
    return {"milestones": result}
