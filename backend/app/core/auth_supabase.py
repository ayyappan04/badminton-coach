"""Supabase Auth token verification.

Supabase issues the tokens; this service verifies them and maps them onto a
local profile row. It never mints Supabase sessions and never holds a user
password — which is the point of migrating: one source of identity, and the
credential handling belongs to the platform that specialises in it.

Verification prefers the asymmetric path (ES256/RS256 against the project's
published JWKS) because it needs no shared secret in this process at all. The
HS256 branch exists only for projects still on a legacy symmetric key.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional

import httpx
import jwt
from jwt import PyJWKClient

from app.core import config

logger = logging.getLogger("app.auth.supabase")

_JWKS_TTL_S = 600
_lock = threading.Lock()
_jwks_client: Optional[PyJWKClient] = None
_jwks_fetched_at: float = 0.0


class SupabaseAuthError(Exception):
    pass


def jwks_url() -> str:
    return f"{config.SUPABASE_URL}/auth/v1/.well-known/jwks.json"


def _client() -> Optional[PyJWKClient]:
    """Cached JWKS client. Refreshed periodically so a key rotation heals
    itself rather than requiring a redeploy."""
    global _jwks_client, _jwks_fetched_at
    if not config.SUPABASE_URL:
        return None
    with _lock:
        if _jwks_client is None or (time.time() - _jwks_fetched_at) > _JWKS_TTL_S:
            try:
                _jwks_client = PyJWKClient(jwks_url(), cache_keys=True)
                _jwks_fetched_at = time.time()
            except Exception:  # noqa: BLE001
                logger.warning("could not build JWKS client", exc_info=True)
                return _jwks_client
    return _jwks_client


def has_jwks() -> bool:
    """Whether this project publishes asymmetric signing keys."""
    if not config.SUPABASE_URL:
        return False
    try:
        with httpx.Client(timeout=5.0) as c:
            r = c.get(jwks_url())
        return r.status_code == 200 and bool((r.json() or {}).get("keys"))
    except Exception:  # noqa: BLE001
        return False


def decode(token: str) -> Optional[Dict[str, Any]]:
    """Verify a Supabase access token. Returns claims, or None.

    Returns None for every failure mode rather than distinguishing them: an
    error that says "expired" versus "bad signature" tells an attacker which
    half of their guess was right.
    """
    if not token or not config.SUPABASE_URL:
        return None

    options = {"require": ["exp", "sub"], "verify_aud": bool(config.SUPABASE_JWT_AUD)}
    common = {
        "audience": config.SUPABASE_JWT_AUD or None,
        "issuer": f"{config.SUPABASE_URL}/auth/v1",
        "options": options,
        "leeway": 10,
    }

    client = _client()
    if client is not None:
        try:
            signing_key = client.get_signing_key_from_jwt(token)
            return jwt.decode(token, signing_key.key,
                              algorithms=["ES256", "RS256"], **common)
        except jwt.PyJWTError:
            pass  # fall through to the symmetric branch
        except Exception:  # noqa: BLE001
            logger.warning("JWKS verification error", exc_info=True)

    if config.SUPABASE_JWT_SECRET:
        try:
            return jwt.decode(token, config.SUPABASE_JWT_SECRET,
                              algorithms=["HS256"], **common)
        except jwt.PyJWTError:
            return None
    return None


def profile_fields(claims: Dict[str, Any]) -> Dict[str, Any]:
    meta = claims.get("user_metadata") or {}
    email = (claims.get("email") or meta.get("email") or "").strip().lower()
    display = (meta.get("display_name") or meta.get("full_name")
               or meta.get("name") or (email.split("@")[0] if email else "Player"))
    return {
        "id": claims.get("sub"),
        "email": email,
        "display_name": str(display)[:120],
        "avatar_url": meta.get("avatar_url"),
        "email_verified": bool(claims.get("email_verified")
                               or meta.get("email_verified")
                               or claims.get("email_confirmed_at")),
    }


def ensure_profile(db, claims: Dict[str, Any]):
    """Get or create the local profile for a verified Supabase identity.

    The profile row's primary key IS the Supabase user id. That single choice
    is what makes the same value work as `videos.owner_user_id`, as
    `auth.uid()` inside an RLS policy, and as the first segment of every
    storage key — so the three layers cannot drift apart.
    """
    from datetime import datetime, timezone
    from app.models.user import ConsentSettings, User

    fields = profile_fields(claims)
    uid = fields["id"]
    if not uid:
        return None

    user = db.get(User, uid)
    if user is None:
        user = db.query(User).filter_by(supabase_user_id=uid).first()

    if user is None and fields["email"]:
        # An account that already exists locally with this email is the
        # cutover case: link it rather than creating a duplicate profile.
        existing = db.query(User).filter(User.email == fields["email"]).first()
        if existing is not None:
            existing.supabase_user_id = uid
            existing.auth_provider = "supabase"
            db.commit()
            return existing

    if user is None:
        user = User(
            id=uid, supabase_user_id=uid, email=fields["email"] or f"{uid}@users.noreply",
            display_name=fields["display_name"], avatar_url=fields["avatar_url"],
            hashed_password=None, auth_provider="supabase",
            email_verified_at=datetime.now(timezone.utc) if fields["email_verified"] else None,
        )
        db.add(user)
        db.flush()
        db.add(ConsentSettings(user_id=user.id))
        db.commit()
        logger.info("created profile for supabase user %s", uid)
        return user

    # Keep the mirrored profile fields current without ever overwriting
    # something the user set in this app with a stale identity-provider value.
    changed = False
    if fields["email"] and user.email != fields["email"]:
        user.email = fields["email"]
        changed = True
    if fields["email_verified"] and user.email_verified_at is None:
        user.email_verified_at = datetime.now(timezone.utc)
        changed = True
    if user.supabase_user_id != uid:
        user.supabase_user_id = uid
        user.auth_provider = "supabase"
        changed = True
    if changed:
        db.commit()
    return user
