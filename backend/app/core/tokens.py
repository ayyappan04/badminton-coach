"""Single-use, expiring tokens for email verification and password reset.

Design notes
------------
* Tokens are 256 bits of `secrets.token_urlsafe` entropy — not guessable and
  not derived from user data.
* Only a SHA-256 hash is persisted. A database leak therefore does not hand an
  attacker working reset links.
* `consume()` is atomic-ish: it marks the row used inside the same transaction
  it validates in, so a token cannot be redeemed twice.
* Issuing a new token of a given purpose invalidates the account's outstanding
  tokens of that purpose, so an old email can't be replayed later.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import String, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column, Session

from app.models.base import TimestampedBase

PURPOSE_VERIFY_EMAIL = "verify_email"
PURPOSE_PASSWORD_RESET = "password_reset"


class OneTimeToken(TimestampedBase):
    __tablename__ = "one_time_tokens"

    user_id: Mapped[str] = mapped_column(String, index=True)
    purpose: Mapped[str] = mapped_column(String, index=True)
    token_hash: Mapped[str] = mapped_column(String, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    used: Mapped[bool] = mapped_column(Boolean, default=False)


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def issue(db: Session, user_id: str, purpose: str, ttl_minutes: int) -> str:
    """Create a token, invalidating any outstanding ones for this purpose."""
    db.query(OneTimeToken).filter(
        OneTimeToken.user_id == user_id,
        OneTimeToken.purpose == purpose,
        OneTimeToken.used == False,  # noqa: E712 (SQL boolean comparison)
    ).update({"used": True})

    raw = secrets.token_urlsafe(32)
    db.add(OneTimeToken(
        user_id=user_id,
        purpose=purpose,
        token_hash=_hash(raw),
        expires_at=_now() + timedelta(minutes=ttl_minutes),
    ))
    db.commit()
    return raw


def consume(db: Session, raw_token: str, purpose: str) -> Optional[str]:
    """Validate and burn a token. Returns the user_id, or None if the token is
    unknown, already used, of the wrong purpose, or expired."""
    if not raw_token:
        return None
    row = db.query(OneTimeToken).filter(
        OneTimeToken.token_hash == _hash(raw_token),
        OneTimeToken.purpose == purpose,
    ).first()
    if row is None or row.used:
        return None

    expires_at = row.expires_at
    if expires_at.tzinfo is None:  # SQLite round-trips naive datetimes
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < _now():
        return None

    row.used = True
    db.commit()
    return row.user_id


def expire_now(raw_token: str) -> None:
    """Test helper: force a token past its expiry without waiting."""
    from app.db.session import SessionLocal
    db = SessionLocal()
    try:
        row = db.query(OneTimeToken).filter(OneTimeToken.token_hash == _hash(raw_token)).first()
        if row is not None:
            row.expires_at = _now() - timedelta(minutes=1)
            db.commit()
    finally:
        db.close()
