import re
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

import jwt
from jwt import InvalidTokenError
from passlib.context import CryptContext

from app.core.config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRE_MINUTES

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# bcrypt silently truncates beyond 72 bytes; reject rather than mislead.
MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LEN = 10

# A small list of obvious choices. Not a substitute for a breach-corpus check
# (e.g. Have I Been Pwned k-anonymity), which is recorded as a next step.
_COMMON_PASSWORDS = {
    "password", "password1", "password123", "12345678", "123456789", "1234567890",
    "qwertyuiop", "letmein123", "iloveyou1", "badminton", "badminton1",
    "shuttlecock", "administrator", "changeme123",
}


def validate_password(password: str, *, email: str = "") -> Tuple[bool, str]:
    """Return (ok, message). Length-first policy: long passphrases beat
    short-but-gnarly ones, so we require length plus basic variety."""
    if len(password) < MIN_PASSWORD_LEN:
        return False, f"Password must be at least {MIN_PASSWORD_LEN} characters."
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return False, "Password is too long (max 72 bytes)."
    if password.lower() in _COMMON_PASSWORDS:
        return False, "That password is too common. Please choose another."
    if email and email.split("@")[0].lower() and email.split("@")[0].lower() in password.lower():
        return False, "Password must not contain your email address."
    classes = sum([
        bool(re.search(r"[a-z]", password)),
        bool(re.search(r"[A-Z]", password)),
        bool(re.search(r"\d", password)),
        bool(re.search(r"[^A-Za-z0-9]", password)),
    ])
    if classes < 3:
        return False, "Use at least three of: lowercase, uppercase, digits, symbols."
    return True, ""


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(password, hashed)
    except ValueError:
        # Malformed/legacy hash — treat as a failed login, never a 500.
        return False


def create_access_token(user_id: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "exp": now + timedelta(minutes=JWT_EXPIRE_MINUTES),
        # Millisecond-precision issue time, used to invalidate tokens minted
        # before a logout or password reset (see models.user.tokens_valid_from).
        "iat_ms": int(now.timestamp() * 1000),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[str]:
    """Backwards-compatible helper: returns the subject or None."""
    claims = decode_access_token_claims(token)
    return claims.get("sub") if claims else None


def decode_access_token_claims(token: str) -> Optional[dict]:
    try:
        # `algorithms` is pinned to the single expected algorithm so a token
        # claiming alg=none or a different family is rejected outright.
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except InvalidTokenError:
        return None


def token_is_current(claims: dict, tokens_valid_from: Optional[datetime]) -> bool:
    """False when the token predates the account's last session-invalidation
    event (logout / password reset)."""
    if tokens_valid_from is None:
        return True
    cutoff = tokens_valid_from
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    issued_ms = claims.get("iat_ms")
    if issued_ms is None:
        # Legacy token minted before this claim existed — cannot prove it is
        # current, so treat it as revoked.
        return False
    return issued_ms >= int(cutoff.timestamp() * 1000)
