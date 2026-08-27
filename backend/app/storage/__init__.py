"""Storage selection. One switch, read once."""
from __future__ import annotations

from functools import lru_cache

from app.core import config
from app.storage.base import (  # noqa: F401  re-exported for callers
    ObjectStat, StorageError, UploadAuthorization, VideoStorage,
    guess_content_type, sha256_file,
)
from app.storage.local import LocalVideoStorage


@lru_cache(maxsize=1)
def get_storage() -> "VideoStorage":
    if config.STORAGE_BACKEND == "supabase":
        from app.storage.supabase_storage import SupabaseVideoStorage
        return SupabaseVideoStorage()
    return LocalVideoStorage()


def reset_storage_cache() -> None:
    """Tests switch backends within one process."""
    get_storage.cache_clear()
