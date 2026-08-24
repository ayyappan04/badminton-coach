from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core import config, tokens as token_store
from app.core.mailer import send_verification_email, send_password_reset_email
from app.core.rate_limit import check as rate_limit_check, client_ip
from app.core.security import (
    hash_password, verify_password, create_access_token, validate_password,
)
from app.db.session import get_db
from app.models.user import User, ConsentSettings

router = APIRouter(prefix="/auth", tags=["auth"])

# Deliberately identical for "no such account" and "wrong password" so the
# endpoint cannot be used to enumerate registered addresses.
_INVALID_CREDENTIALS = "Invalid email or password"
# Identical response whether or not the address exists.
_RESET_ACK = {
    "message": "If an account exists for that address, a password reset link has been sent."
}


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
    display_name: str = Field(min_length=1, max_length=80)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=1, max_length=200)


class ResetRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    avatar_url: Optional[str] = None
    email_verified: bool = False

    class Config:
        from_attributes = True


class TokenOut(BaseModel):
    token: Optional[str]
    user: UserOut
    email_verification_required: bool = False


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id, email=user.email, display_name=user.display_name,
        avatar_url=user.avatar_url, email_verified=user.email_verified_at is not None,
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.post("/register", response_model=TokenOut)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    rate_limit_check(f"register:{client_ip(request)}", config.REGISTER_RATE_LIMIT)

    ok, message = validate_password(payload.password, email=payload.email)
    if not ok:
        raise HTTPException(status_code=400, detail=message)

    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        # Signup necessarily reveals that an address is taken; we keep the
        # message minimal and rate-limit the endpoint to blunt enumeration.
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        display_name=payload.display_name.strip(),
    )
    db.add(user)
    db.flush()
    db.add(ConsentSettings(user_id=user.id))
    db.commit()
    db.refresh(user)

    raw = token_store.issue(
        db, user.id, token_store.PURPOSE_VERIFY_EMAIL, config.EMAIL_VERIFICATION_TTL_MINUTES,
    )
    send_verification_email(user.email, raw)

    # When verification is mandatory we withhold the session token entirely.
    if config.REQUIRE_EMAIL_VERIFICATION:
        return TokenOut(token=None, user=_user_out(user), email_verification_required=True)
    return TokenOut(token=create_access_token(user.id), user=_user_out(user),
                    email_verification_required=False)


@router.post("/login", response_model=TokenOut)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    rate_limit_check(f"login:{client_ip(request)}:{payload.email.lower()}", config.LOGIN_RATE_LIMIT)

    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail=_INVALID_CREDENTIALS)

    if config.REQUIRE_EMAIL_VERIFICATION and user.email_verified_at is None:
        raise HTTPException(
            status_code=403,
            detail="Please verify your email address before signing in. Check your inbox for the verification link.",
        )

    return TokenOut(token=create_access_token(user.id), user=_user_out(user))


@router.post("/logout")
def logout(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Server-side session revocation: every token issued before now stops
    working, so logging out is not merely a client-side token deletion."""
    current_user.tokens_valid_from = _now()
    db.commit()
    return {"logged_out": True}


@router.post("/verify-email")
def verify_email(payload: VerifyEmailRequest, db: Session = Depends(get_db)):
    user_id = token_store.consume(db, payload.token, token_store.PURPOSE_VERIFY_EMAIL)
    if not user_id:
        raise HTTPException(status_code=400, detail="This verification link is invalid or has expired.")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=400, detail="This verification link is invalid or has expired.")
    if user.email_verified_at is None:
        user.email_verified_at = _now()
        db.commit()
    return {"verified": True, "token": create_access_token(user.id), "user": _user_out(user)}


@router.post("/resend-verification")
def resend_verification(payload: ResetRequest, request: Request, db: Session = Depends(get_db)):
    rate_limit_check(f"resend:{client_ip(request)}:{payload.email.lower()}",
                     config.PASSWORD_RESET_RATE_LIMIT)
    user = db.query(User).filter(User.email == payload.email).first()
    if user and user.email_verified_at is None:
        raw = token_store.issue(db, user.id, token_store.PURPOSE_VERIFY_EMAIL,
                                config.EMAIL_VERIFICATION_TTL_MINUTES)
        send_verification_email(user.email, raw)
    return {"message": "If that address needs verification, a new link has been sent."}


@router.post("/request-password-reset")
def request_password_reset(payload: ResetRequest, request: Request, db: Session = Depends(get_db)):
    rate_limit_check(f"reset:{client_ip(request)}:{payload.email.lower()}",
                     config.PASSWORD_RESET_RATE_LIMIT)
    user = db.query(User).filter(User.email == payload.email).first()
    if user:
        raw = token_store.issue(db, user.id, token_store.PURPOSE_PASSWORD_RESET,
                                config.PASSWORD_RESET_TTL_MINUTES)
        send_password_reset_email(user.email, raw)
    # Same body and status either way.
    return _RESET_ACK


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    user_id = token_store.consume(db, payload.token, token_store.PURPOSE_PASSWORD_RESET)
    if not user_id:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired.")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired.")

    ok, message = validate_password(payload.new_password, email=user.email)
    if not ok:
        raise HTTPException(status_code=400, detail=message)

    user.hashed_password = hash_password(payload.new_password)
    # A password reset must end every existing session.
    user.tokens_valid_from = _now()
    # Completing a reset proves control of the mailbox.
    if user.email_verified_at is None:
        user.email_verified_at = _now()
    db.commit()
    return {"reset": True}


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return _user_out(current_user)


@router.get("/users/lookup", response_model=UserOut)
def lookup_user_by_email(
    email: EmailStr = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Used by the friend-request and coach-invite flows.

    Rate-limited per caller because it confirms whether an address has an
    account. Returns only the fields those flows need — never verification
    state or anything else about the target.
    """
    rate_limit_check(f"lookup:{current_user.id}", (20, 3600))
    user = db.query(User).filter(User.email == email).first()
    if not user:
        raise HTTPException(status_code=404, detail="No user found with that email")
    return UserOut(id=user.id, email=user.email, display_name=user.display_name,
                   avatar_url=user.avatar_url, email_verified=False)
