from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User, ConsentSettings
from app.models.video import Video, TrackedPerson, Calibration
from app.models.analysis import PoseFrame, ShuttleFrame, Rally, Shot, CoachingInsight
from app.models.profile import PlayerProfile, ProfileHistorySnapshot
from pathlib import Path

router = APIRouter(tags=["consent"])


class ConsentSettingsOut(BaseModel):
    allow_training_data_contribution: bool
    default_clip_share_scope: str
    default_profile_share_scope: str
    retention_policy: str
    share_progress_with_club: bool

    class Config:
        from_attributes = True


class ConsentSettingsUpdate(BaseModel):
    allow_training_data_contribution: Optional[bool] = None
    default_clip_share_scope: Optional[str] = None
    default_profile_share_scope: Optional[str] = None
    retention_policy: Optional[str] = None
    share_progress_with_club: Optional[bool] = None


def _get_or_create(db: Session, user_id: str) -> ConsentSettings:
    settings = db.query(ConsentSettings).filter_by(user_id=user_id).first()
    if not settings:
        settings = ConsentSettings(user_id=user_id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


@router.get("/consent-settings", response_model=ConsentSettingsOut)
def get_consent_settings(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _get_or_create(db, current_user.id)


@router.patch("/consent-settings", response_model=ConsentSettingsOut)
def update_consent_settings(payload: ConsentSettingsUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    settings = _get_or_create(db, current_user.id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(settings, field, value)
    db.commit()
    db.refresh(settings)
    return settings


@router.delete("/account")
def delete_account(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    videos = db.query(Video).filter_by(owner_user_id=current_user.id).all()
    for video in videos:
        Path(video.storage_path).unlink(missing_ok=True)
        for tp in db.query(TrackedPerson).filter_by(video_id=video.id).all():
            db.query(PoseFrame).filter_by(tracked_person_id=tp.id).delete()
        db.query(TrackedPerson).filter_by(video_id=video.id).delete()
        db.query(Calibration).filter_by(video_id=video.id).delete()
        db.query(ShuttleFrame).filter_by(video_id=video.id).delete()
        db.query(Rally).filter_by(video_id=video.id).delete()
        db.query(Shot).filter_by(video_id=video.id).delete()
        db.query(CoachingInsight).filter_by(video_id=video.id).delete()
        db.delete(video)

    db.query(PlayerProfile).filter_by(user_id=current_user.id).delete()
    db.query(ProfileHistorySnapshot).filter_by(user_id=current_user.id).delete()
    db.query(ConsentSettings).filter_by(user_id=current_user.id).delete()
    db.delete(current_user)
    db.commit()
    return {"deleted": True, "note": "Account, videos, and derived analysis data removed. Any previously licensed training assets from other sources are unaffected."}
