"""Upload hardening: type/size/signature validation and filename safety."""
import io
from pathlib import Path

import pytest

from app.core.config import UPLOADS_DIR


def _upload(client, user, filename, content, content_type="video/mp4", fmt="singles"):
    return client.post(
        "/api/v1/videos",
        files={"file": (filename, io.BytesIO(content), content_type)},
        data={"match_format": fmt},
        headers=user["headers"],
    )


def _real_mp4_bytes(tmp_path) -> bytes:
    import cv2
    import numpy as np
    p = tmp_path / "gen.mp4"
    w = cv2.VideoWriter(str(p), cv2.VideoWriter_fourcc(*"mp4v"), 10, (160, 120))
    for _ in range(5):
        w.write(np.zeros((120, 160, 3), dtype=np.uint8))
    w.release()
    return p.read_bytes()


# --------------------------------------------------------------------------
# Type / signature validation
# --------------------------------------------------------------------------

def test_valid_mp4_accepted(client, user_a, tmp_path):
    r = _upload(client, user_a, "match.mp4", _real_mp4_bytes(tmp_path))
    assert r.status_code == 200, r.text


def test_unsupported_extension_rejected(client, user_a):
    r = _upload(client, user_a, "notes.txt", b"hello", content_type="text/plain")
    assert r.status_code == 400


def test_executable_renamed_to_mp4_is_rejected(client, user_a):
    """Extension allowlists alone are not enough — content must be checked."""
    elf = b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 512
    r = _upload(client, user_a, "payload.mp4", elf)
    assert r.status_code == 400, "non-video content accepted because it was named .mp4"


def test_html_renamed_to_mp4_is_rejected(client, user_a):
    html = b"<html><script>alert(1)</script></html>" + b"A" * 256
    r = _upload(client, user_a, "xss.mp4", html)
    assert r.status_code == 400, "HTML accepted as a video"


def test_empty_file_rejected(client, user_a):
    r = _upload(client, user_a, "empty.mp4", b"")
    assert r.status_code == 400


def test_corrupted_video_rejected_or_marked_failed(client, user_a, tmp_path):
    """Truncated/garbled MP4: either rejected at upload, or accepted and later
    surfaced as a clear failure — never a 500."""
    good = _real_mp4_bytes(tmp_path)
    corrupted = good[:120] + b"\x00" * 400  # keep the ftyp box, destroy the rest
    r = _upload(client, user_a, "corrupt.mp4", corrupted)
    assert r.status_code in (200, 400), f"unexpected status {r.status_code}: {r.text[:200]}"
    assert r.status_code != 500


def test_oversized_upload_rejected(client, user_a, tmp_path):
    from app.core.config import MAX_UPLOAD_BYTES
    header = _real_mp4_bytes(tmp_path)[:64]
    payload = header + b"\x00" * (MAX_UPLOAD_BYTES + 1024)
    r = _upload(client, user_a, "huge.mp4", payload)
    assert r.status_code == 413, f"oversized upload not rejected ({r.status_code})"


def test_oversized_upload_does_not_persist_partial_file(client, user_a, tmp_path):
    from app.core.config import MAX_UPLOAD_BYTES
    before = set(Path(UPLOADS_DIR).glob("*"))
    header = _real_mp4_bytes(tmp_path)[:64]
    _upload(client, user_a, "huge2.mp4", header + b"\x00" * (MAX_UPLOAD_BYTES + 1024))
    after = set(Path(UPLOADS_DIR).glob("*"))
    assert after == before, "a rejected oversized upload left a file on disk"


# --------------------------------------------------------------------------
# Filename safety
# --------------------------------------------------------------------------

@pytest.mark.parametrize("evil", [
    "../../../../etc/passwd.mp4",
    "..\\..\\windows\\system32\\evil.mp4",
    "/etc/cron.d/rooted.mp4",
    "....//....//escape.mp4",
])
def test_path_traversal_filenames_cannot_escape_upload_dir(client, user_a, tmp_path, evil):
    r = _upload(client, user_a, evil, _real_mp4_bytes(tmp_path))
    assert r.status_code in (200, 400)
    if r.status_code == 200:
        from app.db.session import SessionLocal
        from app.models.video import Video
        db = SessionLocal()
        try:
            v = db.get(Video, r.json()["id"])
            stored = Path(v.storage_path).resolve()
            assert stored.parent == Path(UPLOADS_DIR).resolve(), f"file escaped upload dir: {stored}"
        finally:
            db.close()


def test_dangerous_filename_is_neutralised_in_response(client, user_a, tmp_path):
    evil = '<img src=x onerror=alert(1)>.mp4'
    r = _upload(client, user_a, evil, _real_mp4_bytes(tmp_path))
    assert r.status_code in (200, 400)
    if r.status_code == 200:
        returned = r.json()["original_filename"]
        assert "<" not in returned and ">" not in returned, f"raw HTML echoed back: {returned!r}"


def test_crlf_in_filename_cannot_inject_response_headers(client, user_a, user_a2=None, tmp_path=None):
    """A filename with CR/LF must not break out of Content-Disposition."""
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    content = _real_mp4_bytes(tmp)
    evil = "clip\r\nX-Injected: yes\r\n.mp4"
    r = _upload(client, user_a, evil, content)
    if r.status_code != 200:
        return  # rejected outright is also acceptable
    vid = r.json()["id"]
    s = client.get(f"/api/v1/videos/{vid}/stream", params={"token": user_a["token"]})
    assert "x-injected" not in {k.lower() for k in s.headers.keys()}, "response header injection via filename"


def test_very_long_filename_handled(client, user_a, tmp_path):
    r = _upload(client, user_a, "A" * 5000 + ".mp4", _real_mp4_bytes(tmp_path))
    assert r.status_code in (200, 400)
    assert r.status_code != 500


def test_unicode_filename_handled(client, user_a, tmp_path):
    r = _upload(client, user_a, "羽毛球-试合-🏸.mp4", _real_mp4_bytes(tmp_path))
    assert r.status_code in (200, 400)
    assert r.status_code != 500


def test_stored_filename_is_generated_not_user_supplied(client, user_a, tmp_path):
    r = _upload(client, user_a, "user-chosen-name.mp4", _real_mp4_bytes(tmp_path))
    assert r.status_code == 200
    from app.db.session import SessionLocal
    from app.models.video import Video
    db = SessionLocal()
    try:
        v = db.get(Video, r.json()["id"])
        assert "user-chosen-name" not in Path(v.storage_path).name
    finally:
        db.close()


# --------------------------------------------------------------------------
# Quotas
# --------------------------------------------------------------------------

def test_upload_rate_limit_or_quota_enforced(client, make_user, tmp_path):
    """A single account should not be able to fill the disk unbounded."""
    u = make_user("uploadflood")
    content = _real_mp4_bytes(tmp_path)
    codes = [_upload(client, u, f"flood{i}.mp4", content).status_code for i in range(25)]
    assert 429 in codes or 507 in codes, f"no upload quota/rate limit (codes: {sorted(set(codes))})"
