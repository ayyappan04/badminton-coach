from datetime import datetime
from typing import Optional

from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase


class User(TimestampedBase):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String)
    avatar_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Set when the user clicks their verification link.
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Any access token issued before this instant is rejected. Bumped on
    # logout and on password reset so those actions really end a session.
    tokens_valid_from: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ConsentSettings(TimestampedBase):
    __tablename__ = "consent_settings"

    user_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    allow_training_data_contribution: Mapped[bool] = mapped_column(Boolean, default=False)
    default_clip_share_scope: Mapped[str] = mapped_column(String, default="private")
    default_profile_share_scope: Mapped[str] = mapped_column(String, default="friends")
    retention_policy: Mapped[str] = mapped_column(String, default="keep_indefinitely")
    # Phase 3: per-metric team sharing — clubs never see member metrics unless
    # the member opts in here (docs/V2_DESIGN.md §9).
    share_progress_with_club: Mapped[bool] = mapped_column(Boolean, default=False)
