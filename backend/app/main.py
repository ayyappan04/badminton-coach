from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.session import Base, engine
import app.models  # noqa: F401 register all models on Base.metadata
from app.api import auth, videos, profile, technique, community, consent, coach, coach_reviews, integration
from app.seed_content import seed as seed_content

Base.metadata.create_all(engine)
seed_content()

app = FastAPI(title="AI Badminton Coach API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(videos.router, prefix="/api/v1")
app.include_router(profile.router, prefix="/api/v1")
app.include_router(technique.router, prefix="/api/v1")
app.include_router(community.router, prefix="/api/v1")
app.include_router(consent.router, prefix="/api/v1")
app.include_router(coach.router, prefix="/api/v1")
app.include_router(coach_reviews.router, prefix="/api/v1")
app.include_router(integration.router, prefix="/api/v1")


@app.get("/api/v1/health")
def health():
    return {"status": "ok"}
