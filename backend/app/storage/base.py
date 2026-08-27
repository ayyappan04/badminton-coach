"""The storage contract the rest of the application codes against.

The CV pipeline, the API routers and the job runner all speak this interface.
Neither `supabase` nor `httpx` appears anywhere in domain code, which is what
keeps the local test suite runnable with no cloud account and keeps a future
move off Supabase a one-file change.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Iterable, Optional, Protocol


@dataclass
class ObjectStat:
    key: str
    bucket: str
    size_bytes: int
    content_type: Optional[str] = None
    updated_at: Optional[datetime] = None
    etag: Optional[str] = None


@dataclass
class UploadAuthorization:
    """What the browser needs to start uploading, and nothing more.

    Deliberately carries no credential of ours. For the Supabase backend the
    browser authenticates with its own Supabase session token, and Storage RLS
    decides whether the path is writable. The API's role is to allocate the
    path and record intent, never to hand out write access.
    """
    video_id: str
    bucket: str
    object_path: str
    upload_method: str            # "tus" | "put"
    endpoint: str
    expires_at: Optional[datetime] = None
    max_bytes: int = 0
    headers: dict = field(default_factory=dict)


class StorageError(RuntimeError):
    pass


class VideoStorage(Protocol):
    """Object-storage operations used by the control plane and the worker."""

    def authorize_upload(self, *, user_id: str, video_id: str, ext: str,
                         content_type: str, size_bytes: int) -> UploadAuthorization: ...

    def stat(self, bucket: str, key: str) -> Optional[ObjectStat]: ...

    def download_to(self, bucket: str, key: str, dest: Path) -> int:
        """Stream an object to local disk. Never buffers the whole file."""
        ...

    def upload_file(self, bucket: str, key: str, src: Path,
                    content_type: str, cache_control: Optional[str] = None) -> ObjectStat: ...

    def upload_bytes(self, bucket: str, key: str, data: bytes,
                     content_type: str, cache_control: Optional[str] = None) -> ObjectStat: ...

    def signed_read_url(self, bucket: str, key: str, expires_in: int) -> str: ...

    def delete(self, bucket: str, keys: Iterable[str]) -> int: ...

    def list_prefix(self, bucket: str, prefix: str) -> list[ObjectStat]: ...

    def health(self) -> bool: ...


def sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    """Checksum by streaming. A multi-GB original must never be read into RAM
    to be hashed — this is worker-side precisely so the browser doesn't have
    to do it either."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def guess_content_type(ext: str) -> str:
    return {
        "mp4": "video/mp4", "m4v": "video/mp4", "mov": "video/quicktime",
        "avi": "video/x-msvideo", "webm": "video/webm",
        "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
        "json": "application/json", "gz": "application/gzip",
    }.get(ext.lower().lstrip("."), "application/octet-stream")
