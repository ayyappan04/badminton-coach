"""Immutable object-path construction.

Two rules, both load-bearing:

1. A user-supplied filename NEVER contributes to an object key. It is display
   metadata only (`videos.original_filename`). Keys are built from UUIDs the
   server generated.
2. Every key begins with `{owner_user_id}/`. Supabase Storage RLS matches on
   that first path segment, so the prefix is not a convention — it is the
   authorization boundary.
"""
from __future__ import annotations

import posixpath
import re

# Media transform settings evolve independently of the CV algorithms, so
# derived media carries its own version. Bump when a normalization parameter
# changes in a way that makes existing proxies stale.
MEDIA_TRANSFORM_VERSION = "m1"

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SAFE_EXT = re.compile(r"^[a-z0-9]{1,8}$")


def _segment(value: str, what: str) -> str:
    """Reject anything that could alter the shape of a key.

    Traversal, absolute paths and empty segments are all caught here rather
    than being normalised away — a caller passing `..` is a bug worth failing
    loudly, not something to silently repair.
    """
    value = str(value)
    if not _SAFE_SEGMENT.match(value) or ".." in value:
        raise ValueError(f"unsafe {what} path segment: {value!r}")
    return value


def normalized_ext(raw_ext: str) -> str:
    ext = (raw_ext or "").lower().lstrip(".")
    if not _SAFE_EXT.match(ext):
        raise ValueError(f"unsafe extension: {raw_ext!r}")
    return ext


def original_key(user_id: str, video_id: str, ext: str) -> str:
    """video-originals/{user_id}/{video_id}/original.{ext}"""
    return posixpath.join(
        _segment(user_id, "user"), _segment(video_id, "video"),
        f"original.{normalized_ext(ext)}",
    )


def derived_prefix(user_id: str, video_id: str, version: str = MEDIA_TRANSFORM_VERSION) -> str:
    return posixpath.join(
        _segment(user_id, "user"), _segment(video_id, "video"), _segment(version, "version"),
    )


def video_prefix(user_id: str, video_id: str) -> str:
    """Everything belonging to one video, across every version. Used by
    deletion and reconciliation."""
    return posixpath.join(_segment(user_id, "user"), _segment(video_id, "video")) + "/"


def derived_key(user_id: str, video_id: str, name: str, version: str = MEDIA_TRANSFORM_VERSION) -> str:
    return posixpath.join(derived_prefix(user_id, video_id, version), _segment(name, "asset"))


def analysis_key(user_id: str, video_id: str, version: str = MEDIA_TRANSFORM_VERSION) -> str:
    return derived_key(user_id, video_id, "analysis.mp4", version)


def playback_key(user_id: str, video_id: str, version: str = MEDIA_TRANSFORM_VERSION) -> str:
    return derived_key(user_id, video_id, "playback.mp4", version)


def poster_key(user_id: str, video_id: str, version: str = MEDIA_TRANSFORM_VERSION) -> str:
    return derived_key(user_id, video_id, "poster.jpg", version)


def thumbnail_key(user_id: str, video_id: str, version: str = MEDIA_TRANSFORM_VERSION) -> str:
    return derived_key(user_id, video_id, "thumbnail.jpg", version)


def overlay_manifest_key(user_id: str, video_id: str, pipeline_version: str) -> str:
    v = _segment(pipeline_version.replace(".", "_"), "pipeline")
    return posixpath.join(
        _segment(user_id, "user"), _segment(video_id, "video"), v, "overlays", "manifest.json",
    )


def artifact_key(user_id: str, video_id: str, pipeline_version: str, name: str) -> str:
    """Large machine-readable analysis output, e.g. pose_landmarks.json.gz."""
    v = _segment(pipeline_version.replace(".", "_"), "pipeline")
    return posixpath.join(
        _segment(user_id, "user"), _segment(video_id, "video"), v, "artifacts", _segment(name, "artifact"),
    )


def evidence_clip_key(user_id: str, video_id: str, clip_id: str,
                      version: str = MEDIA_TRANSFORM_VERSION) -> str:
    return posixpath.join(
        derived_prefix(user_id, video_id, version), "clips", f"{_segment(clip_id, 'clip')}.mp4",
    )


def owner_of(key: str) -> str:
    """First path segment == owning user id. The single place this mapping is
    decoded, so authorization checks cannot drift from key construction."""
    return key.split("/", 1)[0]
