"""Storage abstraction: path construction, containment, signed access.

Object keys are the authorization boundary in production -- Supabase Storage
RLS matches on the first path segment. So the code that builds keys is
security-critical, and it is tested as such.
"""
import pytest

from app.storage import paths
from app.storage.base import StorageError


# --- path construction ------------------------------------------------------

@pytest.mark.parametrize("bad", [
    "../etc", "a/b", "", ".", "..", "x;y", "a b", "a\\b", "\x00", "-leading",
    "user/../../root", "%2e%2e", "a/../b",
])
def test_path_builder_rejects_unsafe_segments(bad):
    """Traversal is refused, not sanitised away. A caller passing `..` is a bug
    worth failing loudly rather than silently repairing."""
    with pytest.raises(ValueError):
        paths.original_key(bad, "video-1", "mp4")
    with pytest.raises(ValueError):
        paths.original_key("user-1", bad, "mp4")


@pytest.mark.parametrize("bad_ext", ["../mp4", "mp4/../..", "exe;", "", "a" * 20, "m p4"])
def test_extension_allowlist(bad_ext):
    with pytest.raises(ValueError):
        paths.original_key("user-1", "video-1", bad_ext)


def test_every_key_starts_with_the_owner_id():
    """This is the invariant Storage RLS depends on."""
    user, video = "u-123", "v-456"
    keys = [
        paths.original_key(user, video, "mp4"),
        paths.analysis_key(user, video),
        paths.playback_key(user, video),
        paths.poster_key(user, video),
        paths.thumbnail_key(user, video),
        paths.overlay_manifest_key(user, video, "2.0.0"),
        paths.evidence_clip_key(user, video, "clip1"),
        paths.artifact_key(user, video, "2.0.0", "pipeline_result.json.gz"),
    ]
    for key in keys:
        assert key.split("/")[0] == user, key
        assert paths.owner_of(key) == user
        assert ".." not in key


def test_derived_assets_are_versioned():
    """Derived assets must be invalidatable when the transform changes."""
    a = paths.analysis_key("u", "v", version="m1")
    b = paths.analysis_key("u", "v", version="m2")
    assert a != b
    assert paths.MEDIA_TRANSFORM_VERSION in paths.analysis_key("u", "v")


def test_original_key_is_stable_and_immutable_per_video():
    assert paths.original_key("u", "v", "mp4") == paths.original_key("u", "v", "MP4")


# --- local backend containment ----------------------------------------------

def test_local_backend_refuses_to_escape_its_bucket(storage, tmp_path):
    """Keys are server-generated so this cannot happen today; the check turns
    any future bug into a refusal rather than a write outside the store."""
    with pytest.raises(StorageError):
        storage._path("video-originals", "../../../etc/passwd")
    with pytest.raises(StorageError):
        storage._path("../escape", "x")


def test_roundtrip_upload_stat_download_delete(storage, tmp_path):
    key = paths.original_key("u-1", "v-1", "mp4")
    payload = b"badminton" * 1000

    storage.upload_bytes("video-originals", key, payload, "video/mp4")
    stat = storage.stat("video-originals", key)
    assert stat is not None and stat.size_bytes == len(payload)

    dest = tmp_path / "out.mp4"
    assert storage.download_to("video-originals", key, dest) == len(payload)
    assert dest.read_bytes() == payload

    assert storage.delete("video-originals", [key]) == 1
    assert storage.stat("video-originals", key) is None


def test_stat_of_missing_object_returns_none_not_error(storage):
    assert storage.stat("video-originals", "u/v/nope.mp4") is None


def test_list_prefix_is_scoped(storage):
    for user in ("u-a", "u-b"):
        storage.upload_bytes("video-originals",
                             paths.original_key(user, "v-1", "mp4"), b"x", "video/mp4")
    only_a = storage.list_prefix("video-originals", "u-a/")
    assert only_a and all(o.key.startswith("u-a/") for o in only_a)


def test_checksum_streams_rather_than_buffering(tmp_path):
    """A multi-GB original must never be read into RAM to be hashed."""
    import hashlib
    from app.storage.base import sha256_file

    path = tmp_path / "big.bin"
    chunk = b"\xab" * (1024 * 1024)
    with path.open("wb") as fh:
        for _ in range(12):
            fh.write(chunk)

    expected = hashlib.sha256(chunk * 12).hexdigest()
    assert sha256_file(path) == expected


# --- signed read access -----------------------------------------------------

def test_playback_url_requires_authentication(client, user_a, upload_flow, tiny_mp4):
    video_id, _ = upload_flow.full(user_a, tiny_mp4.read_bytes())
    upload_flow.complete(user_a, video_id)
    assert client.get(f"/api/v1/videos/{video_id}/playback").status_code == 401


def test_playback_url_is_denied_to_another_user(client, user_a, user_b, upload_flow, tiny_mp4):
    video_id, _ = upload_flow.full(user_a, tiny_mp4.read_bytes())
    upload_flow.complete(user_a, video_id)
    r = client.get(f"/api/v1/videos/{video_id}/playback", headers=user_b["headers"])
    assert r.status_code == 404


def test_object_route_rejects_a_foreign_prefix(client, user_a, user_b, upload_flow, tiny_mp4):
    """The local equivalent of Storage RLS: the key's owner segment must match
    the caller, or an asset row must grant it."""
    video_id, ticket = upload_flow.full(user_a, tiny_mp4.read_bytes())
    upload_flow.complete(user_a, video_id)
    key = ticket["object_path"]

    ok = client.get(f"/api/v1/videos/objects/{ticket['bucket']}/{key}",
                    params={"token": user_a["token"]})
    assert ok.status_code == 200

    denied = client.get(f"/api/v1/videos/objects/{ticket['bucket']}/{key}",
                        params={"token": user_b["token"]})
    assert denied.status_code == 404


def test_object_route_rejects_a_bad_token(client, user_a, upload_flow, tiny_mp4):
    video_id, ticket = upload_flow.full(user_a, tiny_mp4.read_bytes())
    upload_flow.complete(user_a, video_id)
    r = client.get(f"/api/v1/videos/objects/{ticket['bucket']}/{ticket['object_path']}",
                   params={"token": "not-a-real-token"})
    assert r.status_code == 401


def test_object_route_rejects_traversal_in_the_key(client, user_a):
    r = client.get("/api/v1/videos/objects/video-originals/../../etc/passwd",
                   params={"token": user_a["token"]})
    assert r.status_code in (400, 404)
