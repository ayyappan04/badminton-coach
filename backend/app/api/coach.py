from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.coaching import coach_chat

router = APIRouter(prefix="/coach", tags=["coach"])


class AskRequest(BaseModel):
    question: str


@router.post("/ask")
def ask_coach(payload: AskRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return coach_chat.answer_question(db, current_user.id, payload.question)


@router.get("/suggested-questions")
def suggested_questions(current_user: User = Depends(get_current_user)):
    return {"questions": coach_chat.SUGGESTED_QUESTIONS}
