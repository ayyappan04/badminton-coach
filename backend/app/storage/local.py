"""Filesystem-backed VideoStorage.

Used by the test suite and by `supabase start` local development, so the same
code paths that run in production also run offline. Buckets become
directories; "signed URLs" become the existing authenticated stream route.
"""
from __future__ import annotations

import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional

from app.core import config
from app.storage.base import (
    ObjectStat, StorageError, UploadAuthorization, guess_content_type,
)


class LocalVideoStorage:
    backend = "local"

    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root or config.STORAGE_DIR) / "objects"
        # This backend is the reason the directory needs to exist, so it is
        # the thing that creates it.
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, bucket: str, key: str) -> Path:
        if not bucket or "/" in bucket or ".." in bucket:
            raise StorageError(f"invalid bucket: {bucket!r}")
        base = (self.root / bucket).resolve()
        target = (base / key).resolve()
        # The key is server-generated, but a containment check costs nothing
        # and turns any future bug into a refusal rather than a write outside
        # the store.
        if base != target and base not in target.parents:
            raise StorageError("resolved object path escapes its bucket")
        return target

    def authorize_upload(self, *, user_id: str, video_id: str, ext: str,
                         content_type: str, size_bytes: int) -> UploadAuthorization:
        from app.storage import paths
        key = paths.original_key(user_id, video_id, ext)
        self._path(config.BUCKET_ORIGINALS, key).parent.mkdir(parents=True, exist_ok=True)
        return UploadAuthorization(
            video_id=video_id, bucket=config.BUCKET_ORIGINALS, object_path=key,
            upload_method="put",
            endpoint=f"/api/v1/videos/uploads/{video_id}/bytes",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=config.UPLOAD_SESSION_TTL_S),
            max_bytes=min(size_bytes or config.MAX_VIDEO_BYTES, config.MAX_VIDEO_BYTES),
        )

    def stat(self, bucket: str, key: str) -> Optional[ObjectStat]:
        p = self._path(bucket, key)
        if not p.exists() or not p.is_file():
            return None
        st = p.stat()
        return ObjectStat(
            key=key, bucket=bucket, size_bytes=st.st_size,
            content_type=guess_content_type(p.suffix),
            updated_at=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
        )

    def download_to(self, bucket: str, key: str, dest: Path) -> int:
        src = self._path(bucket, key)
        if not src.exists():
            raise StorageError(f"object not found: {bucket}/{key}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Hard-link when possible: the analysis worker only ever reads the
        # source, so copying gigabytes locally is pure waste.
        try:
            if dest.exists():
                dest.unlink()
            os.link(src, dest)
        except OSError:
            shutil.copyfile(src, dest)
        return dest.stat().st_size

    def upload_file(self, bucket: str, key: str, src: Path, content_type: str,
                    cache_control: Optional[str] = None) -> ObjectStat:
        dest = self._path(bucket, key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        return ObjectStat(key=key, bucket=bucket, size_bytes=dest.stat().st_size,
                          content_type=content_type,
                          updated_at=datetime.now(timezone.utc))

    def upload_bytes(self, bucket: str, key: str, data: bytes, content_type: str,
                     cache_control: Optional[str] = None) -> ObjectStat:
        dest = self._path(bucket, key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return ObjectStat(key=key, bucket=bucket, size_bytes=len(data),
                          content_type=content_type, updated_at=datetime.now(timezone.utc))

    def signed_read_url(self, bucket: str, key: str, expires_in: int) -> str:
        # No CDN locally: playback keeps going through the authenticated API
        # route, which enforces exactly the same ownership rules.
        from urllib.parse import quote
        return f"/api/v1/videos/objects/{quote(bucket)}/{quote(key)}"

    def delete(self, bucket: str, keys: Iterable[str]) -> int:
        removed = 0
        for key in keys:
            p = self._path(bucket, key)
            if p.exists():
                p.unlink()
                removed += 1
        return removed

    def list_prefix(self, bucket: str, prefix: str) -> list[ObjectStat]:
        base = (self.root / bucket).resolve()
        start = self._path(bucket, prefix) if prefix else base
        search_root = start if start.is_dir() else start.parent
        if not search_root.exists():
            return []
        out: list[ObjectStat] = []
        for p in search_root.rglob("*"):
            if not p.is_file():
                continue
            key = str(p.relative_to(base))
            if prefix and not key.startswith(prefix.rstrip("/")):
                continue
            st = p.stat()
            out.append(ObjectStat(key=key, bucket=bucket, size_bytes=st.st_size,
                                  content_type=guess_content_type(p.suffix),
                                  updated_at=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)))
        return out

    def health(self) -> bool:
        return self.root.exists() and os.access(self.root, os.W_OK)
