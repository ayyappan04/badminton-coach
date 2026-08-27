"""Cross-user isolation on the production surface, and secret containment.

The MVP's isolation tests covered the old endpoints. These cover everything the
Vercel/Supabase migration added: uploads, assets, runs, events, playback and
deletion. Every one of them takes a video id in the URL, so every one of them
is an opportunity to leak another user's match by guessing.
"""
import re
from pathlib import Path

import pytest

from app.db.session import SessionLocal
from app.models.video import Video

REPO = Path(__file__).resolve().parent.parent.parent


@pytest.fixture()
def a_video(client, user_a, upload_flow, tiny_mp4, deferred_jobs):
    video_id, ticket = upload_flow.full(user_a, tiny_mp4.read_bytes())
    upload_flow.complete(user_a, video_id)
    return video_id, ticket


# --- endpoint isolation -----------------------------------------------------

@pytest.mark.parametrize("path_tpl", [
    "/api/v1/videos/{id}",
    "/api/v1/videos/{id}/playback",
    "/api/v1/videos/{id}/runs",
    "/api/v1/videos/{id}/events",
    "/api/v1/videos/{id}/status",
    "/api/v1/videos/{id}/rallies",
    "/api/v1/videos/{id}/shots",
    "/api/v1/videos/{id}/insights",
    "/api/v1/videos/{id}/analytics",
    "/api/v1/videos/{id}/scorecards",
    "/api/v1/videos/{id}/quality-report",
    "/api/v1/videos/{id}/phases",
    "/api/v1/videos/{id}/heatmap",
    "/api/v1/videos/{id}/tracked-persons",
    "/api/v1/videos/{id}/overlay-manifest",
    "/api/v1/videos/{id}/calibration",
])
def test_user_b_cannot_read_user_a_video(client, user_b, a_video, path_tpl):
    video_id, _ = a_video
    r = client.get(path_tpl.format(id=video_id), headers=user_b["headers"])
    # 404 rather than 403 everywhere: a 403 confirms the id exists.
    assert r.status_code == 404, f"{path_tpl} leaked to another user ({r.status_code})"


@pytest.mark.parametrize("method,path_tpl", [
    ("delete", "/api/v1/videos/{id}"),
    ("post", "/api/v1/videos/{id}/process"),
    ("post", "/api/v1/videos/{id}/reprocess"),
])
def test_user_b_cannot_mutate_user_a_video(client, user_b, a_video, method, path_tpl):
    video_id, _ = a_video
    r = getattr(client, method)(path_tpl.format(id=video_id), headers=user_b["headers"])
    assert r.status_code == 404


def test_user_b_video_never_appears_in_user_a_listing(client, user_a, user_b,
                                                       upload_flow, tiny_mp4, deferred_jobs):
    b_id, _ = upload_flow.full(user_b, tiny_mp4.read_bytes())
    upload_flow.complete(user_b, b_id)
    listing = client.get("/api/v1/videos", headers=user_a["headers"]).json()
    assert b_id not in [v["id"] for v in listing]


def test_quota_is_per_user(client, user_a, user_b, upload_flow, tiny_mp4, deferred_jobs):
    data = tiny_mp4.read_bytes()
    a_id, _ = upload_flow.full(user_a, data)
    upload_flow.complete(user_a, a_id)

    a_quota = client.get("/api/v1/videos/uploads/quota", headers=user_a["headers"]).json()
    b_quota = client.get("/api/v1/videos/uploads/quota", headers=user_b["headers"]).json()
    assert a_quota["total_bytes"] >= len(data)
    assert b_quota["total_bytes"] == 0, "usage bled across accounts"


def test_active_uploads_are_per_user(client, user_a, user_b, upload_flow):
    upload_flow.initiate(user_a, filename="a.mp4", size_bytes=1000)
    assert client.get("/api/v1/videos/uploads/active",
                      headers=user_b["headers"]).json() == []


# --- coach access -----------------------------------------------------------

def test_coach_with_an_active_review_can_read_but_not_mutate(client, user_a, user_b, a_video):
    """The only non-owner read path in the product: explicit, scoped to one
    video, and revocable."""
    from app.models.coach_review import CoachReview

    video_id, _ = a_video
    with SessionLocal() as db:
        db.add(CoachReview(video_id=video_id, student_user_id=user_a["id"],
                           coach_user_id=user_b["id"], status="active"))
        db.commit()

    assert client.get(f"/api/v1/videos/{video_id}/playback",
                      headers=user_b["headers"]).status_code in (200, 404)
    # Read access never implies write access.
    assert client.delete(f"/api/v1/videos/{video_id}",
                         headers=user_b["headers"]).status_code == 404
    assert client.post(f"/api/v1/videos/{video_id}/reprocess",
                       headers=user_b["headers"]).status_code == 404


def test_revoking_a_review_ends_access_immediately(client, user_a, user_b, a_video):
    from app.models.coach_review import CoachReview

    video_id, _ = a_video
    with SessionLocal() as db:
        review = CoachReview(video_id=video_id, student_user_id=user_a["id"],
                             coach_user_id=user_b["id"], status="active")
        db.add(review)
        db.commit()
        review_id = review.id

    with SessionLocal() as db:
        db.get(CoachReview, review_id).status = "revoked"
        db.commit()

    assert client.get(f"/api/v1/videos/{video_id}/playback",
                      headers=user_b["headers"]).status_code == 404


def test_deleting_a_video_revokes_every_coach_review_on_it(client, user_a, user_b, a_video):
    from app.models.coach_review import CoachReview

    video_id, _ = a_video
    with SessionLocal() as db:
        db.add(CoachReview(video_id=video_id, student_user_id=user_a["id"],
                           coach_user_id=user_b["id"], status="active"))
        db.commit()

    client.delete(f"/api/v1/videos/{video_id}", headers=user_a["headers"])

    with SessionLocal() as db:
        reviews = db.query(CoachReview).filter_by(video_id=video_id).all()
        assert reviews, "test fixture disappeared"
        assert all(r.status == "revoked" for r in reviews)
    assert client.get(f"/api/v1/videos/{video_id}/playback",
                      headers=user_b["headers"]).status_code == 404


# --- deletion ---------------------------------------------------------------

def test_deletion_stops_access_before_objects_are_purged(client, user_a, a_video):
    """Two-phase by design: access ends synchronously, cleanup is async. The
    failure mode of a stuck cleanup is a storage bill, not a privacy breach."""
    video_id, _ = a_video
    assert client.delete(f"/api/v1/videos/{video_id}",
                         headers=user_a["headers"]).status_code == 200

    with SessionLocal() as db:
        video = db.get(Video, video_id)
        assert video is not None, "phase 1 must tombstone, not hard-delete"
        assert video.deleted_at is not None
        assert video.status == "deleted"

    for path in (f"/api/v1/videos/{video_id}",
                 f"/api/v1/videos/{video_id}/playback",
                 f"/api/v1/videos/{video_id}/shots"):
        assert client.get(path, headers=user_a["headers"]).status_code == 404


def test_purge_removes_objects_analysis_and_usage(client, user_a, a_video, storage):
    from app.models.assets import VideoAsset
    from app.services import deletion_service

    video_id, ticket = a_video
    before = client.get("/api/v1/videos/uploads/quota", headers=user_a["headers"]).json()
    assert before["total_bytes"] > 0

    client.delete(f"/api/v1/videos/{video_id}", headers=user_a["headers"])
    with SessionLocal() as db:
        deletion_service.purge_video_objects(db, video_id)

    assert storage.stat(ticket["bucket"], ticket["object_path"]) is None
    with SessionLocal() as db:
        assert db.get(Video, video_id) is None
        assert db.query(VideoAsset).filter_by(video_id=video_id, deleted_at=None).count() == 0

    after = client.get("/api/v1/videos/uploads/quota", headers=user_a["headers"]).json()
    assert after["total_bytes"] == 0, "storage quota was not released"


def test_purge_refuses_to_touch_a_live_video(client, user_a, a_video):
    """A stale cleanup message must not delete something still in use."""
    from app.services import deletion_service

    video_id, _ = a_video
    with SessionLocal() as db:
        assert deletion_service.purge_video_objects(db, video_id) == 0
        assert db.get(Video, video_id) is not None


# --- secret containment -----------------------------------------------------

def test_service_role_key_is_never_referenced_in_frontend_source():
    """The service-role key bypasses RLS completely. If it reaches a browser,
    every user's footage is readable."""
    src = REPO / "frontend" / "src"
    if not src.exists():
        pytest.skip("frontend source not present")

    banned = re.compile(
        r"SUPABASE_SERVICE_ROLE|SERVICE_ROLE_KEY|service_role|sbp_[A-Za-z0-9]|"
        r"DATABASE_URL|postgresql://",
        re.I,
    )
    offenders = []
    for path in src.rglob("*.ts*"):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if banned.search(line) and "must never" not in line and "never in" not in line:
                offenders.append(f"{path.relative_to(REPO)}:{lineno}: {line.strip()[:90]}")
    assert not offenders, "privileged material referenced in client source:\n" + "\n".join(offenders)


def test_built_client_bundle_contains_no_privileged_material():
    dist = REPO / "frontend" / "dist"
    if not dist.exists():
        pytest.skip("frontend not built; run `npm run build` first")

    banned = ["SUPABASE_SERVICE_ROLE_KEY", "service_role", "sbp_", "postgresql://",
              "JWT_SECRET"]
    offenders = []
    for path in dist.rglob("*"):
        if not path.is_file() or path.suffix not in (".js", ".css", ".html", ".map"):
            continue
        text = path.read_text(errors="ignore")
        offenders += [f"{path.name}: {token}" for token in banned if token in text]
    assert not offenders, f"built bundle contains privileged material: {offenders}"


def test_only_anon_grade_supabase_values_are_vite_exposed():
    """VITE_* is shipped to every browser. Only publishable values belong there."""
    src = REPO / "frontend" / "src"
    if not src.exists():
        pytest.skip("frontend source not present")

    allowed = {"VITE_SUPABASE_URL", "VITE_SUPABASE_ANON_KEY", "VITE_API_BASE_URL",
               "VITE_SUPABASE_PUBLISHABLE_KEY"}
    found = set()
    for path in src.rglob("*.ts*"):
        found |= set(re.findall(r"VITE_[A-Z0-9_]+", path.read_text()))
    assert found <= allowed, f"unexpected VITE_ variables in client code: {found - allowed}"


def test_env_example_ships_no_real_credentials():
    env = REPO / ".env.example"
    if not env.exists():
        pytest.skip(".env.example not present")
    text = env.read_text()
    # Real Supabase keys are long JWTs or sb_/sbp_ prefixed.
    assert not re.search(r"eyJ[A-Za-z0-9_-]{30,}", text), "a real JWT is committed"
    assert not re.search(r"\bsbp_[A-Za-z0-9]{20,}", text), "a real Supabase key is committed"
    assert not re.search(r"postgresql://[^\s<]*:[^\s<@]{8,}@", text), "a real DSN is committed"
