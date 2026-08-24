"""Outbound email with a safe-by-default backend.

Backends
--------
`console` (default): nothing leaves the process. Messages are appended to an
in-memory `outbox` and logged. This is what development and the test suite
use, so running the app can never send mail to a real person by accident.

`smtp`: sends via a configured SMTP server. Intended for a *capture* server in
development (MailHog / Mailpit / Mailtrap / Ethereal) and a real provider in
production. Credentials come from the environment only — never hardcoded.

The outbox is intentionally importable by tests (`from app.core.mailer import
outbox`) so the verification/reset flows can be asserted end to end without a
network round-trip.
"""
import logging
import smtplib
from email.message import EmailMessage
from typing import Dict, List, Optional

from app.core import config

logger = logging.getLogger("app.mailer")

# Captured messages when MAIL_BACKEND=console. Each entry:
# {"to", "subject", "body", "token"}
outbox: List[Dict[str, Optional[str]]] = []

MAX_OUTBOX = 500


def send_mail(to: str, subject: str, body: str, token: Optional[str] = None) -> None:
    """Deliver a message via the configured backend.

    `token` is stored alongside console-captured mail purely so tests can
    retrieve the one-time token without parsing the body. It is never sent as
    a separate field over SMTP.
    """
    if config.MAIL_BACKEND == "smtp" and config.SMTP_HOST:
        _send_smtp(to, subject, body)
        # Still record a token-free breadcrumb for debugging.
        logger.info("sent %r to %s via smtp", subject, to)
        return

    outbox.append({"to": to, "subject": subject, "body": body, "token": token})
    del outbox[:-MAX_OUTBOX]
    logger.info("[console-mail] to=%s subject=%s\n%s", to, subject, body)


def _send_smtp(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = config.MAIL_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as server:
        if config.SMTP_USE_TLS:
            server.starttls()
        if config.SMTP_USERNAME:
            server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
        server.send_message(msg)


# --- message templates ------------------------------------------------------

def send_verification_email(to: str, token: str) -> None:
    link = f"{config.APP_BASE_URL}/verify-email?token={token}"
    send_mail(
        to=to,
        subject="Verify your Badminton Coach email",
        body=(
            "Welcome to Badminton Coach.\n\n"
            f"Please verify your email address by opening this link:\n{link}\n\n"
            f"The link expires in {config.EMAIL_VERIFICATION_TTL_MINUTES // 60} hours "
            "and can only be used once.\n\n"
            "If you did not create this account, you can ignore this message."
        ),
        token=token,
    )


def send_password_reset_email(to: str, token: str) -> None:
    link = f"{config.APP_BASE_URL}/reset-password?token={token}"
    send_mail(
        to=to,
        subject="Reset your Badminton Coach password",
        body=(
            "We received a request to reset your Badminton Coach password.\n\n"
            f"Open this link to choose a new one:\n{link}\n\n"
            f"The link expires in {config.PASSWORD_RESET_TTL_MINUTES} minutes and can "
            "only be used once. Resetting your password signs out all existing "
            "sessions.\n\n"
            "If you did not request this, no action is needed — your password has "
            "not changed."
        ),
        token=token,
    )
