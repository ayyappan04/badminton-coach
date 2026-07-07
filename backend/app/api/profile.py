from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.profile import PlayerProfile, ProfileHistorySnapshot

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("")
def get_profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(PlayerProfile).filter_by(user_id=current_user.id).first()
    if not profile:
        return {
            "matches_analyzed_count": 0, "play_style_labels": [], "strengths": [],
            "weaknesses": [], "radar_scores": {}, "training_plan": {},
            "message": "Upload and analyze a match to start building your player profile.",
        }
    return {
        "matches_analyzed_count": profile.matches_analyzed_count,
        "play_style_labels": profile.play_style_labels,
        "strengths": profile.strengths,
        "weaknesses": profile.weaknesses,
        "radar_scores": profile.radar_scores,
        "training_plan": profile.training_plan,
    }


@router.get("/history")
def get_profile_history(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    snapshots = db.query(ProfileHistorySnapshot).filter_by(user_id=current_user.id).order_by(ProfileHistorySnapshot.snapshot_at).all()
    return [{"snapshot_at": s.snapshot_at.isoformat(), "radar_scores": s.radar_scores, "video_id": s.video_id} for s in snapshots]


@router.get("/training-plan")
def get_training_plan(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = db.query(PlayerProfile).filter_by(user_id=current_user.id).first()
    if not profile:
        return {"priority_areas": [], "recommended_drill_tags": [], "weekly_theme": None}
    return profile.training_plan
