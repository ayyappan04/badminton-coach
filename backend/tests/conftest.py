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
# The production switches default to the local implementations, which is what
# these tests exercise. Individual tests flip them explicitly.
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("JOB_BACKEND", "local")
os.environ.setdefault("AUTH_MODE", "legacy")
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


# ===========================================================================
# Production-architecture fixtures
# ===========================================================================

@pytest.fixture()
def db():
    """A session against the test database."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def storage():
    """The configured VideoStorage. Local backend under test."""
    from app.storage import get_storage, reset_storage_cache
    reset_storage_cache()
    yield get_storage()
    reset_storage_cache()


@pytest.fixture()
def ffmpeg_available():
    """Skip media tests when no ffmpeg/ffprobe can be resolved.

    Marked rather than silently passed: a media test that did not run is not
    a media test that succeeded.
    """
    from app.media import ffmpeg
    try:
        ffmpeg.ffmpeg_bin()
        ffmpeg.ffprobe_bin()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ffmpeg/ffprobe unavailable: {exc}")
    return True


@pytest.fixture()
def real_clip(tmp_path, ffmpeg_available):
    """A genuinely encoded H.264 clip, not a hand-built blob.

    Uses ffmpeg's synthetic source so the file has a real moov atom, real
    timestamps and a decodable bitstream -- the properties that make probing
    and normalization meaningful.
    """
    import subprocess
    from app.media import ffmpeg

    path = tmp_path / "clip.mp4"
    subprocess.run([
        ffmpeg.ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=2",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "28",
        "-pix_fmt", "yuv420p", str(path),
    ], check=True)
    assert path.exists() and path.stat().st_size > 0
    return path


def initiate_upload(client, user, *, filename="match.mp4", size_bytes=1024,
                    content_type="video/mp4", match_format="singles", **extra):
    """POST /videos/uploads -- allocate a path and record intent."""
    payload = {
        "filename": filename, "content_type": content_type,
        "size_bytes": size_bytes, "match_format": match_format, **extra,
    }
    return client.post("/api/v1/videos/uploads", json=payload, headers=user["headers"])


def put_bytes(client, user, video_id, data: bytes):
    """Local-backend byte sink, standing in for the browser's direct upload."""
    return client.put(
        f"/api/v1/videos/uploads/{video_id}/bytes",
        content=data,
        headers={**user["headers"], "content-type": "application/octet-stream"},
    )


@pytest.fixture()
def upload_flow(client):
    """Helper bundle for driving the direct-to-storage upload path."""
    class Flow:
        """`client` is bound here so tests read as user actions, not plumbing."""

        @staticmethod
        def initiate(user, **kw):
            return initiate_upload(client, user, **kw)

        @staticmethod
        def put(user, video_id, data: bytes):
            return put_bytes(client, user, video_id, data)

        @staticmethod
        def complete(user, video_id):
            return client.post(f"/api/v1/videos/uploads/{video_id}/complete",
                               headers=user["headers"])

        @staticmethod
        def full(user, data: bytes, **kw):
            """initiate -> upload bytes. Returns (video_id, ticket).

            Stops short of `complete` so a test can assert on the state
            between "bytes landed" and "job queued".
            """
            r = initiate_upload(client, user, size_bytes=len(data), **kw)
            assert r.status_code == 200, r.text
            video_id = r.json()["video_id"]
            assert put_bytes(client, user, video_id, data).status_code == 200
            return video_id, r.json()

    return Flow()


@pytest.fixture()
def deferred_jobs(monkeypatch):
    """Stop the local dispatcher from executing work inline.

    Without this, completing an upload runs the whole pipeline on a background
    thread before the test can assert anything about claiming, leasing or
    retrying -- the test would be racing its own fixture.
    """
    from app.core import config
    from app.jobs import get_dispatcher, reset_dispatcher_cache

    monkeypatch.setattr(config, "JOB_EAGER_LOCAL", False)
    reset_dispatcher_cache()
    yield get_dispatcher()
    reset_dispatcher_cache()


def make_rotated_clip(tmp_path, size="1920x1080", rate=25, duration=1):
    """A clip carrying a 90-degree display rotation, on any ffmpeg version.

    There is no single portable way to author one:
      * `-display_rotation` is an INPUT option added in ffmpeg 6; it is the
        only method that works on 7/8, and does not exist on 5.x.
      * writing the legacy `rotate` tag into a .mov produces a rotation
        side-data on 5.x, but is ignored by 7/8.

    The dev machine and the production image are on opposite sides of that
    split (8.0 vs the 5.1 in Debian bookworm), so the fixture tries both and
    uses whichever actually produced a rotated file. Returns None if neither
    did, so the caller can skip rather than assert against a fixture that
    silently is not testing anything.
    """
    import json
    import subprocess
    from app.media import ffmpeg as ff

    binary = ff.ffmpeg_bin()
    base = tmp_path / "rot_base.mp4"
    subprocess.run([
        binary, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration={duration}",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "30",
        "-pix_fmt", "yuv420p", str(base),
    ], check=True, capture_output=True)

    def rotation_of(path):
        out = subprocess.run(
            [ff.ffprobe_bin(), "-v", "error", "-print_format", "json",
             "-show_streams", str(path)], capture_output=True, text=True).stdout
        try:
            stream = json.loads(out)["streams"][0]
        except (KeyError, IndexError, json.JSONDecodeError):
            return 0
        for side in stream.get("side_data_list") or []:
            if "rotation" in side:
                return abs(int(float(side["rotation"]))) % 360
        tag = (stream.get("tags") or {}).get("rotate")
        return abs(int(float(tag))) % 360 if tag else 0

    candidates = [
        # ffmpeg >= 6
        (tmp_path / "rot_a.mp4",
         [binary, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
          "-display_rotation", "90", "-i", str(base), "-c", "copy"]),
        # ffmpeg 5.x
        (tmp_path / "rot_b.mov",
         [binary, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
          "-i", str(base), "-c", "copy", "-metadata:s:v:0", "rotate=90"]),
    ]
    for dest, argv in candidates:
        result = subprocess.run([*argv, str(dest)], capture_output=True)
        if result.returncode == 0 and dest.exists() and rotation_of(dest) == 90:
            return dest
    return None
