from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.video import Video
from app.models.analysis import CoachingInsight
from app.models.coach_review import CoachReview, CoachNote

router = APIRouter(tags=["coach-reviews"])


class ReviewInvite(BaseModel):
    coach_email: EmailStr
    message: Optional[str] = None


class NoteCreate(BaseModel):
    timestamp_s: float = 0.0
    comment: str
    related_insight_id: Optional[str] = None
    stance: Optional[str] = None  # agree / adjust / disagree


def _active_review_for_coach(db: Session, review_id: str, coach: User) -> CoachReview:
    review = db.get(CoachReview, review_id)
    if not review or review.coach_user_id != coach.id:
        raise HTTPException(status_code=404, detail="Review not found")
    if review.status != "active":
        raise HTTPException(status_code=403, detail="This review is no longer active")
    return review


@router.post("/videos/{video_id}/coach-reviews")
def invite_coach(video_id: str, payload: ReviewInvite,
                 current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    video = db.get(Video, video_id)
    if not video or video.owner_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Video not found")
    coach = db.query(User).filter_by(email=payload.coach_email).first()
    if not coach:
        raise HTTPException(status_code=404, detail="No account exists with that email — your coach needs to sign up first")
    if coach.id == current_user.id:
        raise HTTPException(status_code=400, detail="You can't invite yourself as coach")
    existing = db.query(CoachReview).filter_by(
        video_id=video_id, coach_user_id=coach.id, status="active"
    ).first()
    if existing:
        return {"review_id": existing.id, "status": "active"}
    review = CoachReview(video_id=video_id, student_user_id=current_user.id,
                         coach_user_id=coach.id, message=payload.message)
    db.add(review)
    db.commit()
    return {"review_id": review.id, "status": "active"}


@router.get("/coach-reviews")
def list_reviews(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Both directions: reviews I've been invited to give (as coach) and
    reviews I've requested on my own videos (as student)."""
    as_coach = db.query(CoachReview).filter_by(coach_user_id=current_user.id).all()
    as_student = db.query(CoachReview).filter_by(student_user_id=current_user.id).all()

    def serialize(r: CoachReview):
        video = db.get(Video, r.video_id)
        student = db.get(User, r.student_user_id)
        coach = db.get(User, r.coach_user_id)
        note_count = db.query(CoachNote).filter_by(review_id=r.id).count()
        return {
            "review_id": r.id, "video_id": r.video_id, "status": r.status,
            "video_filename": video.original_filename if video else None,
            "match_format": video.match_format if video else None,
            "student_name": student.display_name if student else None,
            "coach_name": coach.display_name if coach else None,
            "message": r.message, "note_count": note_count,
        }

    return {"as_coach": [serialize(r) for r in as_coach], "as_student": [serialize(r) for r in as_student]}


@router.get("/coach-reviews/{review_id}")
def review_detail(review_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Review-scoped view for the coach: the invited video's AI insights plus
    existing notes. This is the coach's only window into the student's data."""
    review = _active_review_for_coach(db, review_id, current_user)
    video = db.get(Video, review.video_id)
    student = db.get(User, review.student_user_id)
    insights = db.query(CoachingInsight).filter_by(video_id=review.video_id).order_by(CoachingInsight.timestamp_s).all()
    notes = db.query(CoachNote).filter_by(review_id=review.id).order_by(CoachNote.timestamp_s).all()
    return {
        "review_id": review.id,
        "video": {
            "video_id": review.video_id,
            "filename": video.original_filename if video else None,
            "match_format": video.match_format if video else None,
            "duration_seconds": video.duration_seconds if video else None,
        },
        "student_name": student.display_name if student else None,
        "message": review.message,
        "ai_insights": [{
            "insight_id": i.id, "timestamp_s": i.timestamp_s, "category": i.category,
            "observed_action": i.observed_action, "correction": i.correction,
            "confidence": i.confidence,
        } for i in insights],
        "notes": [_serialize_note(n) for n in notes],
    }


@router.post("/coach-reviews/{review_id}/notes")
def add_note(review_id: str, payload: NoteCreate,
             current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    review = _active_review_for_coach(db, review_id, current_user)
    if payload.stance and payload.stance not in ("agree", "adjust", "disagree"):
        raise HTTPException(status_code=400, detail="stance must be agree, adjust, or disagree")
    note = CoachNote(
        review_id=review.id, video_id=review.video_id, coach_user_id=current_user.id,
        timestamp_s=payload.timestamp_s, comment=payload.comment,
        related_insight_id=payload.related_insight_id, stance=payload.stance,
    )
    db.add(note)
    db.commit()
    return _serialize_note(note)


@router.post("/coach-reviews/{review_id}/complete")
def complete_review(review_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    review = _active_review_for_coach(db, review_id, current_user)
    review.status = "completed"
    db.commit()
    return {"status": "completed"}


@router.post("/coach-reviews/{review_id}/revoke")
def revoke_review(review_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Student-side revocation — access ends immediately; the coach's existing
    notes remain visible to the student."""
    review = db.get(CoachReview, review_id)
    if not review or review.student_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Review not found")
    review.status = "revoked"
    db.commit()
    return {"status": "revoked"}


@router.get("/videos/{video_id}/coach-notes")
def video_coach_notes(video_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Student view: all coach notes on their own video, across reviews."""
    video = db.get(Video, video_id)
    if not video or video.owner_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Video not found")
    notes = db.query(CoachNote).filter_by(video_id=video_id).order_by(CoachNote.timestamp_s).all()
    coaches = {n.coach_user_id for n in notes}
    names = {uid: (db.get(User, uid).display_name if db.get(User, uid) else "Coach") for uid in coaches}
    return [dict(_serialize_note(n), coach_name=names.get(n.coach_user_id, "Coach")) for n in notes]


def _serialize_note(n: CoachNote) -> dict:
    return {
        "note_id": n.id, "timestamp_s": n.timestamp_s, "comment": n.comment,
        "related_insight_id": n.related_insight_id, "stance": n.stance,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }
