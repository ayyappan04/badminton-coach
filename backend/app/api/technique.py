from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.coaching_content import TechniqueReference, Drill

router = APIRouter(tags=["technique"])


@router.get("/technique-references")
def list_technique_references(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    refs = db.query(TechniqueReference).all()
    return [{"shot_or_movement_name": r.shot_or_movement_name, "summary": r.summary, "category": r.category} for r in refs]


@router.get("/technique-references/{shot_or_movement}")
def get_technique_reference(
    shot_or_movement: str,
    level: str = Query("intermediate"),        # beginner | intermediate | advanced
    handedness: str = Query("right"),          # right | left
    context: Optional[str] = Query(None),      # attacking | defensive | front_court | rear_court
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ref = db.query(TechniqueReference).filter_by(shot_or_movement_name=shot_or_movement).first()
    if not ref:
        raise HTTPException(status_code=404, detail="No technique reference found for that shot or movement")
    return {
        "shot_or_movement_name": ref.shot_or_movement_name,
        "singles_or_doubles_context": ref.singles_or_doubles_context,
        "category": ref.category,
        "summary": ref.summary,
        "phases": ref.phases,
        "checkpoints": ref.checkpoints,
        "common_beginner_mistakes": ref.common_beginner_mistakes,
        "advanced_variations": ref.advanced_variations,
        "level_note": (ref.level_notes or {}).get(level),
        "context_note": (ref.context_notes or {}).get(context) if context else None,
        "handedness": handedness,  # the client mirrors the reference animation for left-handers
    }


@router.get("/drills")
def list_drills(tag: Optional[str] = Query(None), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    drills = db.query(Drill).all()
    if tag:
        drills = [d for d in drills if tag in (d.target_issue_tags or [])]
    return [{
        "id": d.id, "name": d.name, "category": d.category, "description": d.description,
        "target_issue_tags": d.target_issue_tags, "difficulty": d.difficulty,
    } for d in drills]
