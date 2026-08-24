from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.core.security import decode_access_token_claims, token_is_current
from app.db.session import get_db
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def resolve_user_from_token(db: Session, token: str) -> Optional[User]:
    """Shared token→user resolution, including session-revocation checks.

    Used by the standard dependency and by the video stream endpoint (which
    must accept the token as a query parameter because <video> elements
    cannot send an Authorization header).
    """
    claims = decode_access_token_claims(token)
    if not claims:
        return None
    user_id = claims.get("sub")
    if not user_id:
        return None
    user = db.get(User, user_id)
    if user is None:
        return None
    if not token_is_current(claims, user.tokens_valid_from):
        return None
    return user


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
