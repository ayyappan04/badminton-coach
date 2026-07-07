import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
STORAGE_DIR = BASE_DIR / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
DERIVED_DIR = STORAGE_DIR / "derived"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
DERIVED_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{BASE_DIR / 'app.db'}")

JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 60 * 24 * 7

# Analysis pipeline tunables
FRAME_SAMPLE_FPS = 10          # fps used for detection stages (court/player/tactics)
POSE_SAMPLE_FPS = 15           # fps used for pose + shuttle (motion-sensitive stages)
MAX_VIDEO_DURATION_S = 60 * 30
MIN_RESOLUTION_FOR_SHUTTLE = (640, 360)
