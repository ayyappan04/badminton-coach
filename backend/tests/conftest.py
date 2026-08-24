"""Pytest fixtures for the badminton-coach backend.

Every test run gets an isolated temporary SQLite database and an isolated
upload directory, so tests never touch the developer's real `app.db` or
`storage/uploads`. Environment variables are set BEFORE `app.main` is
imported, because `app.core.config` reads them at import time.
"""
import os
import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

# --- must run before any `app.*` import -------------------------------------
_TMP_ROOT = Path(tempfile.mkdtemp(prefix="bc-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP_ROOT / 'test.db'}"
os.environ["JWT_SECRET"] = "test-only-secret-not-a-real-credential"
os.environ["STORAGE_DIR"] = str(_TMP_ROOT / "storage")
os.environ["BC_DISABLE_RATE_LIMIT"] = "0"
# ----------------------------------------------------------------------------

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _cleanup_tmp():
    yield
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """Rate-limit buckets are process-global; clear them between tests so one
    test's login attempts don't lock out the next test."""
    try:
        from app.core.rate_limit import reset_all
        reset_all()
    except ImportError:
        pass  # rate limiting not yet implemented (baseline runs)
    yield


def _unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


@pytest.fixture()
def make_user(client):
    """Factory: registers a user and returns {email, password, token, id, headers}.

    Uses `verify_directly=True` by default so tests that aren't about email
    verification get a usable session immediately.
    """
    created = []

    def _make(prefix: str = "user", password: str = "CorrectHorse9!battery", verify: bool = True):
        email = _unique_email(prefix)
        r = client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": password, "display_name": prefix.title()},
        )
        assert r.status_code in (200, 201), f"register failed: {r.status_code} {r.text}"
        body = r.json()

        if verify:
            _force_verify(email)

        # Re-login to pick up verified state / obtain a token if register withheld one.
        token = body.get("token")
        if not token:
            lr = client.post("/api/v1/auth/login", json={"email": email, "password": password})
            assert lr.status_code == 200, f"login failed: {lr.status_code} {lr.text}"
            token = lr.json()["token"]

        user = {
            "email": email,
            "password": password,
            "token": token,
            "id": body.get("user", {}).get("id"),
            "headers": {"Authorization": f"Bearer {token}"},
        }
        created.append(user)
        return user

    return _make


def _force_verify(email: str) -> None:
    """Mark an account email-verified directly in the DB (test shortcut that
    skips the mail round-trip). No-op if the column doesn't exist yet."""
    db = SessionLocal()
    try:
        from app.models.user import User
        u = db.query(User).filter(User.email == email).first()
        if u is not None and hasattr(u, "email_verified_at"):
            from datetime import datetime, timezone
            u.email_verified_at = datetime.now(timezone.utc)
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


@pytest.fixture()
def user_a(make_user):
    return make_user("alice")


@pytest.fixture()
def user_b(make_user):
    return make_user("bob")


@pytest.fixture()
def tiny_mp4(tmp_path):
    """A real, decodable 1-second MP4 produced by OpenCV (not a fake blob)."""
    import cv2
    import numpy as np

    path = tmp_path / "clip.mp4"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 240))
    for i in range(10):
        frame = np.full((240, 320, 3), 40, dtype=np.uint8)
        cv2.rectangle(frame, (50 + i, 80), (90 + i, 180), (30, 30, 200), -1)
        writer.write(frame)
    writer.release()
    assert path.exists() and path.stat().st_size > 0
    return path


@pytest.fixture()
def uploaded_video(client, user_a, tiny_mp4):
    """Uploads tiny_mp4 as user_a and returns the created video dict."""
    with tiny_mp4.open("rb") as fh:
        r = client.post(
            "/api/v1/videos",
            files={"file": ("clip.mp4", fh, "video/mp4")},
            data={"match_format": "singles"},
            headers=user_a["headers"],
        )
    assert r.status_code == 200, f"upload failed: {r.status_code} {r.text}"
    return r.json()
