from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core import config
from app.core.security import decode_access_token_claims, token_is_current
from app.db.session import get_db
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def _resolve_legacy(db: Session, token: str) -> Optional[User]:
    """This application's own HS256 tokens, including session revocation."""
    claims = decode_access_token_claims(token)
    if not claims:
        return None
    user_id = claims.get("sub")
    if not user_id:
        return None
    user = db.get(User, user_id)
    if user is None:
        return None
    # A Supabase-native account must never be reachable with a legacy token,
    # whatever a forged `sub` claims.
    if user.auth_provider == "supabase":
        return None
    if not token_is_current(claims, user.tokens_valid_from):
        return None
    return user


def _resolve_supabase(db: Session, token: str) -> Optional[User]:
    """Supabase Auth tokens, verified against the project's signing keys."""
    from app.core import auth_supabase

    claims = auth_supabase.decode(token)
    if not claims:
        return None
    return auth_supabase.ensure_profile(db, claims)


def resolve_user_from_token(db: Session, token: str) -> Optional[User]:
    """Shared token→user resolution.

    AUTH_MODE selects which issuers are trusted:
      legacy   — this app's tokens only (development, tests, pre-cutover)
      supabase — Supabase Auth only (the production target)
      dual     — both, for the cutover window, so existing sessions survive
                 the deploy that flips identity providers

    Also used by the object-read route, which must take the token as a query
    parameter because a <video> element cannot send an Authorization header.
    """
    mode = config.AUTH_MODE
    if mode == "supabase":
        return _resolve_supabase(db, token)
    if mode == "dual":
        # Supabase first: once an account has migrated, that is the identity
        # that matters, and trying it first avoids a pointless local lookup.
        return _resolve_supabase(db, token) or _resolve_legacy(db, token)
    return _resolve_legacy(db, token)


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise _UNAUTHORIZED
    user = resolve_user_from_token(db, creds.credentials)
    if user is None:
        # One generic message for every failure mode (bad signature, expired,
        # revoked, deleted account) so responses reveal nothing extra.
        raise _UNAUTHORIZED
    return user
