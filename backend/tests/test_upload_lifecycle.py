"""Direct-to-storage upload lifecycle.

The property under test throughout: the API allocates and verifies, but never
carries the video. Everything else -- state transitions, idempotency, quota,
refresh recovery -- exists to make that split safe.
"""
import pytest

from app.services import video_state as vs


# --- state machine ----------------------------------------------------------

def test_transition_graph_rejects_illegal_moves():
    class Row:
        status = "analyzed"; stage = None; progress_pct = 0; processing_error = None

    row = Row()
    with pytest.raises(vs.InvalidTransition):
        vs.advance(row, vs.UPLOADING)
    assert row.status == "analyzed", "a rejected transition must not mutate the row"


def test_non_strict_transition_is_ignored_not_raised():
    """The worker races user actions (delete, cancel). Losing that race must
    not crash a job."""
    class Row:
        status = "deleted"; stage = None; progress_pct = 0; processing_error = None

    row = Row()
    assert vs.advance(row, vs.PROCESSING, strict=False) is False
    assert row.status == "deleted"


def test_stale_lease_reclaim_is_a_legal_transition():
    """processing -> queued is how a crashed worker's job returns to the pool.
    If this were illegal the video would be stuck in `processing` forever."""
    assert vs.can(vs.PROCESSING, vs.QUEUED)
    assert vs.can(vs.NORMALIZING, vs.PROCESSING)


def test_every_state_has_a_group_and_label():
    for state in vs.ALL_STATES:
        assert state in vs.GROUP, f"{state} has no UI group"
        assert state in vs.LABEL, f"{state} has no human label"


def test_deleted_is_absorbing():
    assert vs.TRANSITIONS[vs.DELETED] == frozenset()


# --- initiation -------------------------------------------------------------

def test_initiate_returns_coordinates_not_credentials(client, user_a):
    r = client.post("/api/v1/videos/uploads", json={
        "filename": "match.mp4", "content_type": "video/mp4",
        "size_bytes": 5_000_000, "match_format": "singles",
    }, headers=user_a["headers"])
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["bucket"] and body["object_path"]
    assert body["upload_method"] in ("tus", "put")

    # The whole response must not contain anything that grants access on its
    # own. In production the browser authenticates with its own Supabase
    # session and Storage RLS decides.
    blob = str(body).lower()
    for forbidden in ("service_role", "secret", "password", "signature", "sig="):
        assert forbidden not in blob, f"upload authorization leaked {forbidden!r}"


def test_object_path_is_scoped_to_the_owner(client, user_a):
    r = client.post("/api/v1/videos/uploads", json={
        "filename": "../../etc/passwd.mp4", "content_type": "video/mp4",
        "size_bytes": 1000, "match_format": "singles",
    }, headers=user_a["headers"])
    assert r.status_code == 200
    path = r.json()["object_path"]

    # Storage RLS matches on the first segment, so this is the authorization
    # boundary, not a naming convention.
    assert path.startswith(f"{user_a['id']}/"), path
    assert ".." not in path
    assert "passwd" not in path, "user filename must never reach the object key"


def test_declared_filename_is_display_metadata_only(client, user_a):
    r = client.post("/api/v1/videos/uploads", json={
        "filename": "<script>alert(1)</script>.mp4", "content_type": "video/mp4",
        "size_bytes": 1000, "match_format": "singles",
    }, headers=user_a["headers"])
    assert r.status_code == 200
    video = client.get(f"/api/v1/videos/{r.json()['video_id']}",
                       headers=user_a["headers"]).json()
    assert "<script>" not in video["original_filename"]


def test_rejects_unsupported_extension(client, user_a):
    r = client.post("/api/v1/videos/uploads", json={
        "filename": "payload.sh", "content_type": "video/mp4",
        "size_bytes": 1000, "match_format": "singles",
    }, headers=user_a["headers"])
    assert r.status_code == 400


def test_rejects_invalid_match_format(client, user_a):
    r = client.post("/api/v1/videos/uploads", json={
        "filename": "m.mp4", "content_type": "video/mp4",
        "size_bytes": 1000, "match_format": "'; DROP TABLE videos; --",
    }, headers=user_a["headers"])
    assert r.status_code == 400


def test_rejects_file_larger_than_the_hard_limit(client, user_a):
    from app.core import config
    r = client.post("/api/v1/videos/uploads", json={
        "filename": "huge.mp4", "content_type": "video/mp4",
        "size_bytes": config.MAX_VIDEO_BYTES + 1, "match_format": "singles",
    }, headers=user_a["headers"])
    assert r.status_code == 413


# --- completion -------------------------------------------------------------

def test_complete_verifies_the_object_actually_landed(client, user_a):
    """The control plane must not take the client's word for it."""
    r = client.post("/api/v1/videos/uploads", json={
        "filename": "m.mp4", "content_type": "video/mp4",
        "size_bytes": 1000, "match_format": "singles",
    }, headers=user_a["headers"])
    video_id = r.json()["video_id"]

    # No bytes were uploaded. Completion must refuse.
    done = client.post(f"/api/v1/videos/uploads/{video_id}/complete",
                       headers=user_a["headers"])
    assert done.status_code == 409
    assert "upload" in done.json()["detail"].lower()


def test_complete_rejects_a_truncated_upload(client, user_a, upload_flow):
    """A part-uploaded MP4 often still probes; catching the size mismatch here
    turns a confusing CV failure into an accurate message."""
    r = client.post("/api/v1/videos/uploads", json={
        "filename": "m.mp4", "content_type": "video/mp4",
        "size_bytes": 10_000, "match_format": "singles",
    }, headers=user_a["headers"])
    video_id = r.json()["video_id"]

    upload_flow.put(user_a, video_id, b"\x00" * 4_000)   # short
    done = upload_flow.complete(user_a, video_id)
    assert done.status_code == 409


def test_complete_is_idempotent(client, user_a, upload_flow, tiny_mp4):
    """Double-clicking the upload button is not an exotic scenario."""
    data = tiny_mp4.read_bytes()
    video_id, _ = upload_flow.full(user_a, data)

    first = upload_flow.complete(user_a, video_id)
    assert first.status_code == 200
    run_one = first.json()["analysis_run_id"]

    second = upload_flow.complete(user_a, video_id)
    assert second.status_code == 200
    assert second.json()["analysis_run_id"] == run_one, "second call started a second pipeline"

    from app.db.session import SessionLocal
    from app.models.runs import AnalysisRun
    with SessionLocal() as db:
        assert db.query(AnalysisRun).filter_by(video_id=video_id).count() == 1


def test_completion_records_an_original_asset_and_usage(client, user_a, upload_flow, tiny_mp4):
    data = tiny_mp4.read_bytes()
    video_id, _ = upload_flow.full(user_a, data)
    upload_flow.complete(user_a, video_id)

    from app.db.session import SessionLocal
    from app.models.assets import ORIGINAL, VideoAsset
    with SessionLocal() as db:
        asset = db.query(VideoAsset).filter_by(video_id=video_id, asset_type=ORIGINAL).first()
        assert asset is not None
        assert asset.size_bytes == len(data)
        assert asset.owner_user_id == user_a["id"]

    quota = client.get("/api/v1/videos/uploads/quota", headers=user_a["headers"]).json()
    assert quota["original_bytes"] >= len(data)
    assert quota["total_bytes"] >= len(data)


# --- cancel and recovery ----------------------------------------------------

def test_cancel_releases_the_concurrency_slot(client, user_a):
    r = client.post("/api/v1/videos/uploads", json={
        "filename": "m.mp4", "content_type": "video/mp4",
        "size_bytes": 1000, "match_format": "singles",
    }, headers=user_a["headers"])
    video_id = r.json()["video_id"]

    assert len(client.get("/api/v1/videos/uploads/active",
                          headers=user_a["headers"]).json()) == 1
    assert client.post(f"/api/v1/videos/uploads/{video_id}/cancel",
                       headers=user_a["headers"]).status_code == 200
    assert client.get("/api/v1/videos/uploads/active",
                      headers=user_a["headers"]).json() == []


def test_active_uploads_survive_a_client_restart(client, user_a, upload_flow):
    """No essential upload state lives only in React memory."""
    r = client.post("/api/v1/videos/uploads", json={
        "filename": "long.mp4", "content_type": "video/mp4",
        "size_bytes": 50_000, "match_format": "singles",
    }, headers=user_a["headers"])
    video_id = r.json()["video_id"]
    upload_flow.put(user_a, video_id, b"\x00" * 20_000)

    # A brand-new "browser session" asks the server what was in flight.
    active = client.get("/api/v1/videos/uploads/active", headers=user_a["headers"]).json()
    assert len(active) == 1
    assert active[0]["video_id"] == video_id
    assert active[0]["received_size_bytes"] == 20_000
    assert active[0]["expected_size_bytes"] == 50_000


def test_concurrent_upload_cap_is_enforced(client, user_a):
    from app.core import config
    for i in range(config.MAX_ACTIVE_UPLOADS_PER_USER):
        r = client.post("/api/v1/videos/uploads", json={
            "filename": f"m{i}.mp4", "content_type": "video/mp4",
            "size_bytes": 1000, "match_format": "singles",
        }, headers=user_a["headers"])
        assert r.status_code == 200, r.text

    over = client.post("/api/v1/videos/uploads", json={
        "filename": "one-too-many.mp4", "content_type": "video/mp4",
        "size_bytes": 1000, "match_format": "singles",
    }, headers=user_a["headers"])
    assert over.status_code == 429


# --- authorization ----------------------------------------------------------

def test_upload_endpoints_require_authentication(client):
    assert client.post("/api/v1/videos/uploads", json={
        "filename": "m.mp4", "content_type": "video/mp4",
        "size_bytes": 1000, "match_format": "singles",
    }).status_code == 401
    assert client.get("/api/v1/videos/uploads/active").status_code == 401
    assert client.get("/api/v1/videos/uploads/quota").status_code == 401


def test_user_b_cannot_drive_user_a_upload(client, user_a, user_b):
    r = client.post("/api/v1/videos/uploads", json={
        "filename": "m.mp4", "content_type": "video/mp4",
        "size_bytes": 1000, "match_format": "singles",
    }, headers=user_a["headers"])
    video_id = r.json()["video_id"]

    for method, path in [
        ("put", f"/api/v1/videos/uploads/{video_id}/bytes"),
        ("post", f"/api/v1/videos/uploads/{video_id}/complete"),
        ("post", f"/api/v1/videos/uploads/{video_id}/cancel"),
        ("post", f"/api/v1/videos/uploads/{video_id}/progress"),
    ]:
        fn = getattr(client, method)
        kwargs = {"headers": user_b["headers"]}
        if method == "put":
            kwargs["content"] = b"x"
        elif "progress" in path:
            kwargs["json"] = {"received_bytes": 1}
        res = fn(path, **kwargs)
        # 404, never 403: a 403 confirms the id exists, turning id enumeration
        # into an existence oracle.
        assert res.status_code == 404, f"{method.upper()} {path} -> {res.status_code}"
