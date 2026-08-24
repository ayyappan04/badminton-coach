"""Authentication tests: signup, login, logout, verification, reset, limits."""
import pytest


# --------------------------------------------------------------------------
# Signup
# --------------------------------------------------------------------------

def test_signup_with_valid_email_succeeds(client):
    r = client.post("/api/v1/auth/register", json={
        "email": "valid-signup@example.com", "password": "CorrectHorse9!battery", "display_name": "Valid",
    })
    assert r.status_code == 200, r.text
    assert "user" in r.json()


def test_signup_with_invalid_email_rejected(client):
    r = client.post("/api/v1/auth/register", json={
        "email": "not-an-email", "password": "CorrectHorse9!battery", "display_name": "Bad",
    })
    assert r.status_code == 422


def test_signup_with_duplicate_email_rejected(client):
    payload = {"email": "dupe@example.com", "password": "CorrectHorse9!battery", "display_name": "Dupe"}
    assert client.post("/api/v1/auth/register", json=payload).status_code == 200
    r2 = client.post("/api/v1/auth/register", json=payload)
    assert r2.status_code == 400


def test_signup_rejects_weak_password(client):
    r = client.post("/api/v1/auth/register", json={
        "email": "weakpw@example.com", "password": "123", "display_name": "Weak",
    })
    assert r.status_code in (400, 422), f"weak password was accepted: {r.status_code}"


def test_password_is_not_returned_or_stored_in_plaintext(client):
    pw = "CorrectHorse9!battery"
    r = client.post("/api/v1/auth/register", json={
        "email": "hashcheck@example.com", "password": pw, "display_name": "Hash",
    })
    assert pw not in r.text
    from app.db.session import SessionLocal
    from app.models.user import User
    db = SessionLocal()
    try:
        u = db.query(User).filter(User.email == "hashcheck@example.com").first()
        assert u is not None
        assert u.hashed_password != pw
        assert u.hashed_password.startswith("$2")  # bcrypt
    finally:
        db.close()


# --------------------------------------------------------------------------
# Login / session
# --------------------------------------------------------------------------

def test_login_with_valid_credentials(client, make_user):
    u = make_user("loginok")
    r = client.post("/api/v1/auth/login", json={"email": u["email"], "password": u["password"]})
    assert r.status_code == 200
    assert r.json()["token"]


def test_login_with_wrong_password_fails(client, make_user):
    u = make_user("wrongpw")
    r = client.post("/api/v1/auth/login", json={"email": u["email"], "password": "TotallyWrong1!"})
    assert r.status_code == 401


def test_login_error_does_not_reveal_whether_account_exists(client, make_user):
    u = make_user("enum")
    existing = client.post("/api/v1/auth/login", json={"email": u["email"], "password": "TotallyWrong1!"})
    missing = client.post("/api/v1/auth/login", json={"email": "nobody-here@example.com", "password": "TotallyWrong1!"})
    assert existing.status_code == missing.status_code == 401
    assert existing.json()["detail"] == missing.json()["detail"], "login response enables account enumeration"


def test_me_requires_authentication(client):
    assert client.get("/api/v1/auth/me").status_code in (401, 403)


def test_me_returns_current_user(client, user_a):
    r = client.get("/api/v1/auth/me", headers=user_a["headers"])
    assert r.status_code == 200
    assert r.json()["email"] == user_a["email"]


def test_tampered_token_rejected(client, user_a):
    bad = user_a["token"][:-3] + "aaa"
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {bad}"})
    assert r.status_code in (401, 403)


def test_token_signed_with_wrong_secret_rejected(client, user_a):
    """A token forged with a different signing key must not be accepted."""
    import jwt
    from datetime import datetime, timedelta, timezone
    forged = jwt.encode(
        {"sub": user_a["id"], "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        "attacker-guessed-secret", algorithm="HS256",
    )
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code in (401, 403)


def test_expired_token_rejected(client, user_a):
    import jwt
    from datetime import datetime, timedelta, timezone
    from app.core.config import JWT_SECRET, JWT_ALGORITHM
    expired = jwt.encode(
        {"sub": user_a["id"], "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        JWT_SECRET, algorithm=JWT_ALGORITHM,
    )
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert r.status_code in (401, 403)


def test_logout_endpoint_exists_and_revokes_session(client, make_user):
    """Logout must invalidate the presented token server-side, not just drop
    it client-side."""
    u = make_user("logout")
    assert client.get("/api/v1/auth/me", headers=u["headers"]).status_code == 200
    r = client.post("/api/v1/auth/logout", headers=u["headers"])
    assert r.status_code == 200, "no server-side logout endpoint"
    after = client.get("/api/v1/auth/me", headers=u["headers"])
    assert after.status_code in (401, 403), "token still valid after logout"


# --------------------------------------------------------------------------
# Email verification
# --------------------------------------------------------------------------

def test_registration_sends_verification_email_in_test_mode(client):
    from app.core.mailer import outbox
    outbox.clear()
    client.post("/api/v1/auth/register", json={
        "email": "verifyme@example.com", "password": "CorrectHorse9!battery", "display_name": "V",
    })
    assert len(outbox) == 1, "no verification email captured"
    assert "verifyme@example.com" == outbox[0]["to"]
    assert "verify" in outbox[0]["body"].lower()


def test_verification_token_works_and_is_single_use(client):
    from app.core.mailer import outbox
    outbox.clear()
    client.post("/api/v1/auth/register", json={
        "email": "single-use@example.com", "password": "CorrectHorse9!battery", "display_name": "S",
    })
    token = outbox[0]["token"]
    first = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert first.status_code == 200, first.text
    second = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert second.status_code == 400, "verification token was reusable"


def test_verification_rejects_unknown_token(client):
    r = client.post("/api/v1/auth/verify-email", json={"token": "not-a-real-token"})
    assert r.status_code == 400


def test_expired_verification_token_rejected(client):
    from app.core.mailer import outbox
    from app.core.tokens import expire_now
    outbox.clear()
    client.post("/api/v1/auth/register", json={
        "email": "expired-verify@example.com", "password": "CorrectHorse9!battery", "display_name": "E",
    })
    token = outbox[0]["token"]
    expire_now(token)
    r = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert r.status_code == 400


# --------------------------------------------------------------------------
# Password reset
# --------------------------------------------------------------------------

def test_password_reset_request_is_generic_for_unknown_account(client, make_user):
    """Reset must not disclose whether an address is registered."""
    u = make_user("resetenum")
    known = client.post("/api/v1/auth/request-password-reset", json={"email": u["email"]})
    unknown = client.post("/api/v1/auth/request-password-reset", json={"email": "ghost@example.com"})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json(), "reset response enables account enumeration"


def test_password_reset_flow_changes_password(client, make_user):
    from app.core.mailer import outbox
    u = make_user("resetflow")
    outbox.clear()
    client.post("/api/v1/auth/request-password-reset", json={"email": u["email"]})
    assert len(outbox) == 1
    token = outbox[0]["token"]

    new_pw = "BrandNewPass42!x"
    r = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": new_pw})
    assert r.status_code == 200, r.text

    assert client.post("/api/v1/auth/login", json={"email": u["email"], "password": u["password"]}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"email": u["email"], "password": new_pw}).status_code == 200


def test_password_reset_token_is_single_use(client, make_user):
    from app.core.mailer import outbox
    u = make_user("resetreuse")
    outbox.clear()
    client.post("/api/v1/auth/request-password-reset", json={"email": u["email"]})
    token = outbox[0]["token"]
    assert client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "FirstNewPass1!"}).status_code == 200
    second = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "SecondNewPass1!"})
    assert second.status_code == 400, "reset token was reusable"


def test_expired_reset_token_rejected(client, make_user):
    from app.core.mailer import outbox
    from app.core.tokens import expire_now
    u = make_user("resetexpiry")
    outbox.clear()
    client.post("/api/v1/auth/request-password-reset", json={"email": u["email"]})
    token = outbox[0]["token"]
    expire_now(token)
    r = client.post("/api/v1/auth/reset-password", json={"token": token, "new_password": "AnotherPass1!"})
    assert r.status_code == 400


def test_password_reset_revokes_existing_sessions(client, make_user):
    from app.core.mailer import outbox
    u = make_user("resetrevoke")
    assert client.get("/api/v1/auth/me", headers=u["headers"]).status_code == 200
    outbox.clear()
    client.post("/api/v1/auth/request-password-reset", json={"email": u["email"]})
    client.post("/api/v1/auth/reset-password", json={"token": outbox[0]["token"], "new_password": "RotatedPass9!"})
    after = client.get("/api/v1/auth/me", headers=u["headers"])
    assert after.status_code in (401, 403), "old session survived a password reset"


# --------------------------------------------------------------------------
# Rate limiting
# --------------------------------------------------------------------------

def test_login_is_rate_limited(client, make_user):
    u = make_user("bruteforce")
    codes = [
        client.post("/api/v1/auth/login", json={"email": u["email"], "password": f"Wrong{i}!aaa"}).status_code
        for i in range(12)
    ]
    assert 429 in codes, f"no rate limiting on login (codes: {codes})"


def test_password_reset_is_rate_limited(client, make_user):
    u = make_user("resetflood")
    codes = [
        client.post("/api/v1/auth/request-password-reset", json={"email": u["email"]}).status_code
        for _ in range(12)
    ]
    assert 429 in codes, f"no rate limiting on password reset (codes: {codes})"
