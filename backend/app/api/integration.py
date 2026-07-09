"""Phase 4 public integration API: scoped, revocable, read-only keys so a
club, coach, or federation tool can pull a player's summary data with the
player's explicit consent (they create and hand over the key, and can revoke
it any time). Keys are hashed at rest and the router exposes GET endpoints
only — raw video is never available through an API key.
"""
import hashlib
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.video import Video
from app.models.analysis import MatchAnalytics
from app.models.profile import PlayerProfile
from app.models.api_key import ApiKey

router = APIRouter(tags=["integration"])


# ---- Key management (session-authenticated) ----

class ApiKeyCreate(BaseModel):
    name: str
    scopes: str = "profile:read,matches:read"


@router.post("/integration/keys")
def create_key(payload: ApiKeyCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    plaintext = f"bck_{secrets.token_urlsafe(32)}"
    key = ApiKey(
        user_id=current_user.id, name=payload.name,
        key_hash=hashlib.sha256(plaintext.encode()).hexdigest(),
        key_prefix=plaintext[:8], scopes=payload.scopes,
    )
    db.add(key)
    db.commit()
    # The only time the plaintext is ever returned.
    return {"key_id": key.id, "api_key": plaintext, "scopes": key.scopes,
            "note": "Store this key now — it cannot be shown again. Revoke it any time."}


@router.get("/integration/keys")
def list_keys(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    keys = db.query(ApiKey).filter_by(user_id=current_user.id).order_by(ApiKey.created_at.desc()).all()
    return [{
        "key_id": k.id, "name": k.name, "key_prefix": k.key_prefix, "scopes": k.scopes,
        "revoked": k.revoked_at is not None,
        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
    } for k in keys]


@router.post("/integration/keys/{key_id}/revoke")
def revoke_key(key_id: str, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    key = db.get(ApiKey, key_id)
    if not key or key.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Key not found")
    key.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {"revoked": True}


# ---- Key-authenticated read-only endpoints ----

def _key_user(required_scope: str):
    def dependency(x_api_key: Optional[str] = Header(None), db: Session = Depends(get_db)) -> User:
        if not x_api_key:
            raise HTTPException(status_code=401, detail="Missing X-API-Key header")
        key = db.query(ApiKey).filter_by(key_hash=hashlib.sha256(x_api_key.encode()).hexdigest()).first()
        if not key or key.revoked_at is not None:
            raise HTTPException(status_code=401, detail="Invalid or revoked API key")
        if required_scope not in [s.strip() for s in key.scopes.split(",")]:
            raise HTTPException(status_code=403, detail=f"This key lacks the {required_scope} scope")
        key.last_used_at = datetime.now(timezone.utc)
        db.commit()
        user = db.get(User, key.user_id)
        if not user:
            raise HTTPException(status_code=401, detail="Key owner no longer exists")
        return user
    return dependency


@router.get("/integration/v1/profile")
def integration_profile(user: User = Depends(_key_user("profile:read")), db: Session = Depends(get_db)):
    profile = db.query(PlayerProfile).filter_by(user_id=user.id).first()
    if not profile:
        return {"display_name": user.display_name, "matches_analyzed": 0}
    return {
        "display_name": user.display_name,
        "matches_analyzed": profile.matches_analyzed_count,
        "radar_scores": profile.radar_scores,
        "play_style_labels": profile.play_style_labels,
        "strengths": profile.strengths,
        "weaknesses": profile.weaknesses,
        "note": "Scores are video-derived estimates with per-dimension confidence — not validated performance metrics.",
    }


@router.get("/integration/v1/matches")
def integration_matches(user: User = Depends(_key_user("matches:read")), db: Session = Depends(get_db)):
    videos = db.query(Video).filter_by(owner_user_id=user.id, status="analyzed").order_by(Video.created_at.desc()).all()
    out = []
    for v in videos:
        ma = db.query(MatchAnalytics).filter_by(video_id=v.id).first()
        rally_stats = (ma.analytics.get("blocks", {}).get("rally_stats", {}) if ma else {})
        out.append({
            "match_id": v.id, "filename": v.original_filename, "format": v.match_format,
            "opponent": v.opponent_name, "result": v.result_summary,
            "quality_score": v.quality_score, "pipeline_version": v.pipeline_version,
            "rally_count": rally_stats.get("rally_count"),
            "avg_rally_duration_s": rally_stats.get("avg_duration_s"),
        })
    return {"matches": out, "note": "Read-only summaries. Raw video and frame-level data are not available via API keys."}
