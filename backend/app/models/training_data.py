from typing import Optional
from datetime import datetime

from sqlalchemy import String, Text, DateTime, JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedBase


class TrainingAsset(TimestampedBase):
    """A piece of footage approved for model training. Physically and permission-wise
    separate from user-uploaded `Video` rows — see docs/PRIVACY_AND_CONSENT.md."""

    __tablename__ = "training_assets"

    source: Mapped[str] = mapped_column(String)  # licensed_broadcast/open_license/internally_collected/user_opt_in
    source_url_or_reference: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    license_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    license_terms_url: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    usage_restrictions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rights_holder: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    consent_record_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    storage_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    added_by_user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    review_status: Mapped[str] = mapped_column(String, default="pending")  # pending/approved/rejected


class ConsentRecord(TimestampedBase):
    __tablename__ = "consent_records"

    subject_type: Mapped[str] = mapped_column(String)  # training_asset/user_video_contribution
    subject_id: Mapped[str] = mapped_column(String, index=True)
    consenting_party: Mapped[str] = mapped_column(String)
    consent_text_snapshot: Mapped[str] = mapped_column(Text)
    granted_at: Mapped[datetime] = mapped_column(DateTime)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class Annotation(TimestampedBase):
    __tablename__ = "annotations"

    training_asset_id: Mapped[str] = mapped_column(String, index=True)
    annotator_user_id: Mapped[str] = mapped_column(String)
    annotation_type: Mapped[str] = mapped_column(String)  # player/court/racket/shuttle/shot
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="draft")  # draft/reviewed/approved/rejected
