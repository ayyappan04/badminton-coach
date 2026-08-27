"""Supabase Storage backed VideoStorage.

Uses the Storage REST API directly rather than the `supabase-py` SDK: the
surface needed here is small, and a thin client keeps the dependency and the
failure modes visible. All calls use the service-role key, which bypasses RLS
— correct for a trusted worker, and the reason this module must never be
importable from anything that runs in a browser.

Note the asymmetry in the upload path: the API never uploads originals. It
allocates a key and lets the browser TUS-upload directly with its own Supabase
session token, so the bytes never touch this process.
"""
from __future__ import annotations

import posixpath
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import quote

import httpx

from app.core import config
from app.storage.base import ObjectStat, StorageError, UploadAuthorization

_TIMEOUT = httpx.Timeout(connect=10.0, read=300.0, write=300.0, pool=10.0)


def _iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class SupabaseVideoStorage:
    backend = "supabase"

    def __init__(self, url: Optional[str] = None, service_key: Optional[str] = None):
        self.url = (url or config.SUPABASE_URL).rstrip("/")
        self.key = service_key or config.SUPABASE_SERVICE_ROLE_KEY
        if not self.url or not self.key:
            raise StorageError(
                "STORAGE_BACKEND=supabase requires SUPABASE_URL and "
                "SUPABASE_SERVICE_ROLE_KEY to be set."
            )
        self.base = f"{self.url}/storage/v1"

    # -- internals ---------------------------------------------------------

    def _headers(self, extra: Optional[dict] = None) -> dict:
        h = {"Authorization": f"Bearer {self.key}", "apikey": self.key}
        if extra:
            h.update(extra)
        return h

    @staticmethod
    def _encode(key: str) -> str:
        # Encode each segment; the slashes are structural.
        return "/".join(quote(part, safe="") for part in key.split("/"))

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=_TIMEOUT, follow_redirects=True)

    # -- interface ---------------------------------------------------------

    def authorize_upload(self, *, user_id: str, video_id: str, ext: str,
                         content_type: str, size_bytes: int) -> UploadAuthorization:
        from app.storage import paths
        key = paths.original_key(user_id, video_id, ext)
        return UploadAuthorization(
            video_id=video_id,
            bucket=config.BUCKET_ORIGINALS,
            object_path=key,
            upload_method="tus",
            endpoint=f"{self.base}/upload/resumable",
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=config.UPLOAD_SESSION_TTL_S),
            max_bytes=config.MAX_VIDEO_BYTES,
            # The browser sends its OWN Supabase access token here. Storage RLS
            # then checks that the first path segment equals auth.uid(), so a
            # tampered object_path is rejected by the database, not by us.
            headers={"x-upsert": "false"},
        )

    def stat(self, bucket: str, key: str) -> Optional[ObjectStat]:
        prefix = posixpath.dirname(key)
        name = posixpath.basename(key)
        with self._client() as c:
            r = c.post(
                f"{self.base}/object/list/{quote(bucket, safe='')}",
                headers=self._headers({"Content-Type": "application/json"}),
                json={"prefix": prefix, "search": name, "limit": 100,
                      "sortBy": {"column": "name", "order": "asc"}},
            )
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            raise StorageError(f"list failed ({r.status_code}): {r.text[:200]}")
        for entry in r.json() or []:
            if entry.get("name") != name:
                continue
            meta = entry.get("metadata") or {}
            # A row with no metadata is a directory placeholder, not an object.
            if not meta:
                return None
            return ObjectStat(
                key=key, bucket=bucket,
                size_bytes=int(meta.get("size") or 0),
                content_type=meta.get("mimetype"),
                updated_at=_iso(entry.get("updated_at")),
                etag=(meta.get("eTag") or "").strip('"') or None,
            )
        return None

    def download_to(self, bucket: str, key: str, dest: Path) -> int:
        dest.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        with self._client() as c:
            with c.stream("GET", f"{self.base}/object/{quote(bucket, safe='')}/{self._encode(key)}",
                          headers=self._headers()) as r:
                if r.status_code >= 400:
                    raise StorageError(f"download failed ({r.status_code}) for {bucket}/{key}")
                with dest.open("wb") as fh:
                    # 8 MiB chunks: large enough to keep the socket busy, small
                    # enough that peak memory is unrelated to file size.
                    for chunk in r.iter_bytes(8 * 1024 * 1024):
                        fh.write(chunk)
                        total += len(chunk)
        return total

    def upload_file(self, bucket: str, key: str, src: Path, content_type: str,
                    cache_control: Optional[str] = None) -> ObjectStat:
        headers = self._headers({
            "Content-Type": content_type,
            # Derived keys are versioned and immutable, so a long max-age is
            # safe. Privacy is preserved because the URL is signed and short
            # lived — the CDN caches the object, not the authorization.
            "Cache-Control": cache_control or "max-age=31536000, immutable",
            "x-upsert": "true",
        })
        size = src.stat().st_size
        with self._client() as c, src.open("rb") as fh:
            r = c.post(f"{self.base}/object/{quote(bucket, safe='')}/{self._encode(key)}",
                       headers=headers, content=fh)
        if r.status_code >= 400:
            raise StorageError(f"upload failed ({r.status_code}) for {bucket}/{key}: {r.text[:200]}")
        return ObjectStat(key=key, bucket=bucket, size_bytes=size,
                          content_type=content_type, updated_at=datetime.now(timezone.utc))

    def upload_bytes(self, bucket: str, key: str, data: bytes, content_type: str,
                     cache_control: Optional[str] = None) -> ObjectStat:
        headers = self._headers({
            "Content-Type": content_type,
            "Cache-Control": cache_control or "max-age=31536000, immutable",
            "x-upsert": "true",
        })
        with self._client() as c:
            r = c.post(f"{self.base}/object/{quote(bucket, safe='')}/{self._encode(key)}",
                       headers=headers, content=data)
        if r.status_code >= 400:
            raise StorageError(f"upload failed ({r.status_code}) for {bucket}/{key}: {r.text[:200]}")
        return ObjectStat(key=key, bucket=bucket, size_bytes=len(data),
                          content_type=content_type, updated_at=datetime.now(timezone.utc))

    def signed_read_url(self, bucket: str, key: str, expires_in: int) -> str:
        with self._client() as c:
            r = c.post(
                f"{self.base}/object/sign/{quote(bucket, safe='')}/{self._encode(key)}",
                headers=self._headers({"Content-Type": "application/json"}),
                json={"expiresIn": int(expires_in)},
            )
        if r.status_code >= 400:
            raise StorageError(f"sign failed ({r.status_code}) for {bucket}/{key}")
        signed = (r.json() or {}).get("signedURL") or ""
        if not signed:
            raise StorageError("sign returned no URL")
        return f"{self.base}{signed}" if signed.startswith("/") else signed

    def delete(self, bucket: str, keys: Iterable[str]) -> int:
        keys = [k for k in keys if k]
        if not keys:
            return 0
        with self._client() as c:
            r = c.request(
                "DELETE", f"{self.base}/object/{quote(bucket, safe='')}",
                headers=self._headers({"Content-Type": "application/json"}),
                json={"prefixes": keys},
            )
        if r.status_code >= 400:
            raise StorageError(f"delete failed ({r.status_code}): {r.text[:200]}")
        body = r.json()
        return len(body) if isinstance(body, list) else len(keys)

    def list_prefix(self, bucket: str, prefix: str) -> list[ObjectStat]:
        """Recursive listing. The Storage list API is one directory level at a
        time, so this walks. Used by reconciliation and deletion, never on a
        request path."""
        out: list[ObjectStat] = []
        pending = [prefix.rstrip("/")]
        seen: set[str] = set()
        with self._client() as c:
            while pending:
                current = pending.pop()
                if current in seen:
                    continue
                seen.add(current)
                offset = 0
                while True:
                    r = c.post(
                        f"{self.base}/object/list/{quote(bucket, safe='')}",
                        headers=self._headers({"Content-Type": "application/json"}),
                        json={"prefix": current, "limit": 100, "offset": offset,
                              "sortBy": {"column": "name", "order": "asc"}},
                    )
                    if r.status_code >= 400:
                        raise StorageError(f"list failed ({r.status_code}): {r.text[:200]}")
                    entries = r.json() or []
                    for entry in entries:
                        name = entry.get("name")
                        if not name:
                            continue
                        key = f"{current}/{name}" if current else name
                        meta = entry.get("metadata") or {}
                        if meta:
                            out.append(ObjectStat(
                                key=key, bucket=bucket,
                                size_bytes=int(meta.get("size") or 0),
                                content_type=meta.get("mimetype"),
                                updated_at=_iso(entry.get("updated_at")),
                            ))
                        else:
                            pending.append(key)   # folder
                    if len(entries) < 100:
                        break
                    offset += 100
        return out

    def health(self) -> bool:
        try:
            with self._client() as c:
                r = c.get(f"{self.base}/bucket", headers=self._headers(),
                          timeout=httpx.Timeout(10.0))
            return r.status_code < 400
        except Exception:
            return False
