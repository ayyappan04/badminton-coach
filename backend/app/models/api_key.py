from datetime import datetime
from typing import Optional

from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase


class ApiKey(TimestampedBase):
    """Scoped, revocable integration key (Phase 4). Only the SHA-256 hash is
    stored — the plaintext key is shown once at creation. Keys are read-only
    by construction: the integration router exposes only GET endpoints, and
    the scope field further restricts which of those a key may call."""

    __tablename__ = "api_keys"

    user_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String)
    key_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    key_prefix: Mapped[str] = mapped_column(String)  # first 8 chars, for display
    scopes: Mapped[str] = mapped_column(String, default="profile:read,matches:read")
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
