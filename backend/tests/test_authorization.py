"""Authorization and per-user data isolation.

These are the "User A must not reach User B's data" tests. They exercise the
real HTTP surface, not internal helpers, because UI hiding and service-layer
filtering are not access control.
"""
import pytest

# Every per-video endpoint that must enforce ownership server-side.
VIDEO_SCOPED_GET_ROUTES = [
    "/api/v1/videos/{vid}",
    "/api/v1/videos/{vid}/status",
    "/api/v1/videos/{vid}/insights",
    "/api/v1/videos/{vid}/analytics",
    "/api/v1/videos/{vid}/rallies",
    "/api/v1/videos/{vid}/shots",
    "/api/v1/videos/{vid}/phases",
    "/api/v1/videos/{vid}/scorecards",
    "/api/v1/videos/{vid}/heatmap",
    "/api/v1/videos/{vid}/calibration",
    "/api/v1/videos/{vid}/quality-report",
    "/api/v1/videos/{vid}/overlay-manifest",
    "/api/v1/videos/{vid}/tracked-persons",
    "/api/v1/videos/{vid}/coach-notes",
]

PROTECTED_ENDPOINTS_NO_AUTH = [
    ("GET", "/api/v1/videos"),
    ("GET", "/api/v1/profile"),
    ("GET", "/api/v1/friends"),
    ("GET", "/api/v1/consent-settings"),
    ("GET", "/api/v1/coach-reviews"),
    ("GET", "/api/v1/integration/keys"),
    ("POST", "/api/v1/coach/ask"),
]


# --------------------------------------------------------------------------
# Unauthenticated access
# --------------------------------------------------------------------------

@pytest.mark.parametrize("method,path", PROTECTED_ENDPOINTS_NO_AUTH)
def test_protected_endpoints_reject_anonymous(client, method, path):
    r = client.request(method, path, json={} if method == "POST" else None)
    assert r.status_code in (401, 403), f"{method} {path} reachable anonymously ({r.status_code})"


def test_anonymous_cannot_upload_video(client, tiny_mp4):
    with tiny_mp4.open("rb") as fh:
        r = client.post("/api/v1/videos", files={"file": ("clip.mp4", fh, "video/mp4")})
    assert r.status_code in (401, 403)


def test_anonymous_cannot_read_results(client, uploaded_video):
    vid = uploaded_video["id"]
    for tmpl in VIDEO_SCOPED_GET_ROUTES:
        r = client.get(tmpl.format(vid=vid))
        assert r.status_code in (401, 403), f"{tmpl} readable anonymously"


# --------------------------------------------------------------------------
# Cross-user isolation
# --------------------------------------------------------------------------

def test_user_b_cannot_read_user_a_video_endpoints(client, uploaded_video, user_b):
    vid = uploaded_video["id"]
    for tmpl in VIDEO_SCOPED_GET_ROUTES:
        r = client.get(tmpl.format(vid=vid), headers=user_b["headers"])
        assert r.status_code in (403, 404), f"{tmpl} leaked to another user ({r.status_code})"


def test_user_b_cannot_see_user_a_video_in_listing(client, uploaded_video, user_b):
    r = client.get("/api/v1/videos", headers=user_b["headers"])
    assert r.status_code == 200
    assert uploaded_video["id"] not in [v["id"] for v in r.json()]


def test_user_b_cannot_delete_user_a_video(client, uploaded_video, user_a, user_b):
    vid = uploaded_video["id"]
    r = client.delete(f"/api/v1/videos/{vid}", headers=user_b["headers"])
    assert r.status_code in (403, 404)
    # ...and it still exists for its owner
    assert client.get(f"/api/v1/videos/{vid}", headers=user_a["headers"]).status_code == 200


def test_user_b_cannot_process_user_a_video(client, uploaded_video, user_b):
    r = client.post(f"/api/v1/videos/{uploaded_video['id']}/process", headers=user_b["headers"])
    assert r.status_code in (403, 404)


def test_user_b_cannot_patch_user_a_calibration(client, uploaded_video, user_b):
    r = client.patch(
        f"/api/v1/videos/{uploaded_video['id']}/calibration",
        json={"court_corners_px": [[0, 0], [10, 0], [10, 10], [0, 10]]},
        headers=user_b["headers"],
    )
    assert r.status_code in (403, 404)


def test_user_b_cannot_compare_using_user_a_video(client, uploaded_video, user_b, tiny_mp4):
    """Compare takes two ids; the caller must own both."""
    with tiny_mp4.open("rb") as fh:
        own = client.post("/api/v1/videos", files={"file": ("mine.mp4", fh, "video/mp4")},
                          headers=user_b["headers"]).json()
    r = client.get(f"/api/v1/videos/compare/{own['id']}/{uploaded_video['id']}", headers=user_b["headers"])
    assert r.status_code in (403, 404), "compare leaked another user's match"


# --------------------------------------------------------------------------
# Video stream access control
# --------------------------------------------------------------------------

def test_stream_requires_a_token(client, uploaded_video):
    r = client.get(f"/api/v1/videos/{uploaded_video['id']}/stream")
    assert r.status_code in (401, 403, 422)


def test_stream_rejects_other_users_token(client, uploaded_video, user_b):
    r = client.get(f"/api/v1/videos/{uploaded_video['id']}/stream", params={"token": user_b["token"]})
    assert r.status_code in (403, 404), "another user could stream the video file"


def test_stream_rejects_garbage_token(client, uploaded_video):
    r = client.get(f"/api/v1/videos/{uploaded_video['id']}/stream", params={"token": "nope"})
    assert r.status_code in (401, 403, 404)


def test_owner_can_stream_own_video(client, uploaded_video, user_a):
    r = client.get(f"/api/v1/videos/{uploaded_video['id']}/stream", params={"token": user_a["token"]})
    assert r.status_code == 200
    assert r.content, "stream returned no bytes"


# --------------------------------------------------------------------------
# Coach review scoping (the one legitimate cross-user path)
# --------------------------------------------------------------------------

def test_coach_review_grants_then_revokes_access(client, uploaded_video, user_a, user_b):
    vid = uploaded_video["id"]
    # Before invitation: no access.
    assert client.get(f"/api/v1/videos/{vid}/stream", params={"token": user_b["token"]}).status_code in (403, 404)

    inv = client.post(f"/api/v1/videos/{vid}/coach-reviews",
                      json={"coach_email": user_b["email"]}, headers=user_a["headers"])
    assert inv.status_code == 200, inv.text
    review_id = inv.json()["review_id"]

    # During an active review the coach can read the review + stream.
    assert client.get(f"/api/v1/coach-reviews/{review_id}", headers=user_b["headers"]).status_code == 200
    assert client.get(f"/api/v1/videos/{vid}/stream", params={"token": user_b["token"]}).status_code == 200

    # A review does NOT grant the whole account.
    assert client.get("/api/v1/videos", headers=user_b["headers"]).status_code == 200
    assert vid not in [v["id"] for v in client.get("/api/v1/videos", headers=user_b["headers"]).json()]

    # After revocation access ends immediately.
    assert client.post(f"/api/v1/coach-reviews/{review_id}/revoke", headers=user_a["headers"]).status_code == 200
    assert client.get(f"/api/v1/coach-reviews/{review_id}", headers=user_b["headers"]).status_code in (403, 404)
    assert client.get(f"/api/v1/videos/{vid}/stream", params={"token": user_b["token"]}).status_code in (403, 404)


def test_non_invited_user_cannot_open_review(client, uploaded_video, user_a, user_b, make_user):
    stranger = make_user("stranger")
    inv = client.post(f"/api/v1/videos/{uploaded_video['id']}/coach-reviews",
                      json={"coach_email": user_b["email"]}, headers=user_a["headers"])
    review_id = inv.json()["review_id"]
    r = client.get(f"/api/v1/coach-reviews/{review_id}", headers=stranger["headers"])
    assert r.status_code in (403, 404)


def test_student_only_can_revoke_own_review(client, uploaded_video, user_a, user_b, make_user):
    stranger = make_user("meddler")
    inv = client.post(f"/api/v1/videos/{uploaded_video['id']}/coach-reviews",
                      json={"coach_email": user_b["email"]}, headers=user_a["headers"])
    review_id = inv.json()["review_id"]
    r = client.post(f"/api/v1/coach-reviews/{review_id}/revoke", headers=stranger["headers"])
    assert r.status_code in (403, 404)


# --------------------------------------------------------------------------
# Integration API keys
# --------------------------------------------------------------------------

def test_integration_endpoints_require_a_key(client):
    assert client.get("/api/v1/integration/v1/profile").status_code in (401, 403)
    assert client.get("/api/v1/integration/v1/matches").status_code in (401, 403)


def test_integration_key_is_scoped_to_its_owner(client, uploaded_video, user_b):
    key = client.post("/api/v1/integration/keys", json={"name": "bob-key"},
                      headers=user_b["headers"]).json()["api_key"]
    r = client.get("/api/v1/integration/v1/matches", headers={"X-API-Key": key})
    assert r.status_code == 200
    assert uploaded_video["id"] not in [m["match_id"] for m in r.json()["matches"]]


def test_revoked_integration_key_stops_working(client, user_a):
    created = client.post("/api/v1/integration/keys", json={"name": "temp"},
                          headers=user_a["headers"]).json()
    key = created["api_key"]
    assert client.get("/api/v1/integration/v1/profile", headers={"X-API-Key": key}).status_code == 200
    client.post(f"/api/v1/integration/keys/{created['key_id']}/revoke", headers=user_a["headers"])
    assert client.get("/api/v1/integration/v1/profile", headers={"X-API-Key": key}).status_code in (401, 403)


def test_integration_key_not_stored_in_plaintext(client, user_a):
    created = client.post("/api/v1/integration/keys", json={"name": "hashcheck"},
                          headers=user_a["headers"]).json()
    from app.db.session import SessionLocal
    from app.models.api_key import ApiKey
    db = SessionLocal()
    try:
        row = db.get(ApiKey, created["key_id"])
        assert row.key_hash != created["api_key"]
        assert created["api_key"] not in row.key_hash
    finally:
        db.close()


def test_user_b_cannot_revoke_user_a_key(client, user_a, user_b):
    created = client.post("/api/v1/integration/keys", json={"name": "alice-key"},
                          headers=user_a["headers"]).json()
    r = client.post(f"/api/v1/integration/keys/{created['key_id']}/revoke", headers=user_b["headers"])
    assert r.status_code in (403, 404)
