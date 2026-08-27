"""Deleting a video, and deleting an account.

Deletion spans two systems that cannot share a transaction. Rather than
pretending otherwise, it is split into two phases with different guarantees:

  Phase 1 (synchronous, transactional in Postgres)
      tombstone the video, revoke every share and coach review, cancel queued
      work. Access stops here. This is the phase the user is waiting on.

  Phase 2 (asynchronous, idempotent, retryable)
      remove analysis rows and storage objects, release quota.

If phase 2 never runs, the user still cannot see or reach the video, and
reconciliation will find the orphaned objects. The failure mode is a storage
bill, not a privacy breach — which is the correct way round.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.core.observability import log
from app.jobs import JobMessage, OP_CLEANUP, get_dispatcher
from app.models.analysis import (
    CoachingInsight, MatchAnalytics, PoseFrame, Rally, Shot, ShuttleFrame,
)
from app.models.assets import VideoAsset
from app.models.coach_review import CoachNote, CoachReview
from app.models.runs import AnalysisRun, ProcessingEvent
from app.models.video import Calibration, TrackedPerson, Video
from app.services import events, usage_service, video_state as vs
from app.storage import get_storage
from app.storage.paths import video_prefix

logger = logging.getLogger("app.deletion")


def soft_delete_video(db: Session, video: Video, *, enqueue_cleanup: bool = True) -> None:
    """Phase 1. Returns as soon as the video is unreachable."""
    now = datetime.now(timezone.utc)

    # Revoke sharing before anything else: a coach must lose access at the
    # same instant the owner does, not whenever cleanup happens to run.
    reviews = db.query(CoachReview).filter_by(video_id=video.id).all()
    for review in reviews:
        review.status = "revoked"

    from app.models.community import SharedClip
    db.query(SharedClip).filter_by(video_id=video.id).update(
        {SharedClip.visibility: "private"}, synchronize_session=False)

    # Stop queued work; a cancelled run must not be reclaimed later.
    db.query(AnalysisRun).filter(
        AnalysisRun.video_id == video.id,
        AnalysisRun.status.in_(("pending", "claimed", "running")),
    ).update({AnalysisRun.status: "cancelled", AnalysisRun.completed_at: now},
             synchronize_session=False)

    video.deleted_at = now
    vs.advance(video, vs.DELETED, strict=False)

    events.record(db, video_id=video.id, owner_user_id=video.owner_user_id,
                  event_type=events.CANCELLED, message="video deleted by owner",
                  commit=False)
    db.commit()

    log(logger, logging.INFO, "video tombstoned", video_id=video.id,
        reviews_revoked=len(reviews))

    if enqueue_cleanup:
        get_dispatcher().enqueue(JobMessage(operation=OP_CLEANUP, video_id=video.id))


def purge_video_objects(db: Session, video_id: str) -> int:
    """Phase 2. Idempotent: safe to run repeatedly, and safe to run on a video
    whose objects are already gone."""
    video = db.get(Video, video_id)
    if video is None:
        return 0
    if video.deleted_at is None:
        # Refuse to purge a live video. A cleanup message that outlived its
        # reason must not delete something the user can still see.
        log(logger, logging.WARNING, "refusing to purge a live video", video_id=video_id)
        return 0

    storage = get_storage()
    removed = 0
    assets = db.query(VideoAsset).filter_by(video_id=video_id).all()

    by_bucket: dict[str, list[str]] = {}
    for asset in assets:
        if asset.deleted_at is None:
            by_bucket.setdefault(asset.storage_bucket, []).append(asset.storage_path)

    for bucket, keys in by_bucket.items():
        try:
            removed += storage.delete(bucket, keys)
        except Exception:  # noqa: BLE001 — reconciliation is the safety net
            log(logger, logging.WARNING, "object delete failed", bucket=bucket,
                keys=len(keys))

    # Sweep anything under the video's prefix that has no asset row: a crash
    # between "object uploaded" and "row written" leaves exactly that.
    if video.owner_user_id:
        prefix = video_prefix(video.owner_user_id, video_id)
        for bucket in {a.storage_bucket for a in assets} or {video.storage_bucket}:
            if not bucket:
                continue
            try:
                stray = [o.key for o in storage.list_prefix(bucket, prefix)]
                if stray:
                    removed += storage.delete(bucket, stray)
            except Exception:  # noqa: BLE001
                pass

    now = datetime.now(timezone.utc)
    for asset in assets:
        if asset.deleted_at is None:
            usage_service.add_asset_bytes(db, asset.owner_user_id, asset.asset_type,
                                          -(asset.size_bytes or 0))
            asset.deleted_at = now

    for model in (PoseFrame, ShuttleFrame, Shot, Rally, CoachingInsight,
                  MatchAnalytics, TrackedPerson, Calibration):
        db.query(model).filter_by(video_id=video_id).delete(synchronize_session=False)

    for note in db.query(CoachNote).filter_by(video_id=video_id).all():
        db.delete(note)
    db.query(CoachReview).filter_by(video_id=video_id).delete(synchronize_session=False)
    db.query(ProcessingEvent).filter_by(video_id=video_id).delete(synchronize_session=False)

    from app.services.analysis_service import _pipeline_cache, _track_id_map_cache
    _pipeline_cache.pop(video_id, None)
    _track_id_map_cache.pop(video_id, None)

    db.delete(video)
    db.commit()

    log(logger, logging.INFO, "video purged", video_id=video_id, objects_removed=removed)
    return removed


def delete_account(db: Session, user_id: str) -> dict:
    """Complete account erasure. Idempotent, so a partially-failed run can
    simply be repeated."""
    from app.models.community import (
        Challenge, ClubMembership, Friendship, PracticePlan, SharedClip,
    )
    from app.models.corrections import UserCorrection
    from app.models.profile import PlayerProfile, ProfileHistorySnapshot
    from app.models.user import ConsentSettings, User
    from app.models.api_key import ApiKey
    from app.models.assets import StorageUsage, UploadSession

    summary = {"videos": 0, "objects": 0}

    for video in db.query(Video).filter_by(owner_user_id=user_id).all():
        if video.deleted_at is None:
            soft_delete_video(db, video, enqueue_cleanup=False)
        summary["objects"] += purge_video_objects(db, video.id)
        summary["videos"] += 1

    # Reviews this user performed FOR other people are their data, not this
    # user's; the link is severed rather than the note destroyed.
    db.query(CoachReview).filter_by(coach_user_id=user_id).update(
        {CoachReview.status: "revoked"}, synchronize_session=False)

    for model, column in (
        (ProfileHistorySnapshot, "user_id"), (PlayerProfile, "user_id"),
        (ConsentSettings, "user_id"), (UserCorrection, "user_id"),
        (PracticePlan, "created_by_user_id"), (ApiKey, "user_id"),
        (ClubMembership, "user_id"), (StorageUsage, "user_id"),
        (UploadSession, "user_id"), (SharedClip, "created_by_user_id"),
    ):
        db.query(model).filter(getattr(model, column) == user_id).delete(synchronize_session=False)

    db.query(Friendship).filter(
        (Friendship.user_id_a == user_id) | (Friendship.user_id_b == user_id)
    ).delete(synchronize_session=False)
    db.query(Challenge).filter(
        (Challenge.created_by_user_id == user_id) | (Challenge.opponent_user_id == user_id)
    ).delete(synchronize_session=False)

    user = db.get(User, user_id)
    if user is not None:
        db.delete(user)
    db.commit()

    log(logger, logging.INFO, "account deleted", user_id=user_id, **summary)
    return summary


def apply_retention(db: Session, *, dry_run: bool = True) -> list[dict]:
    """Originals past their retention window, whose derived assets are verified
    present.

    Never deletes an original for a video that has not been successfully
    analyzed, and never for one whose analysis proxy is missing — losing the
    source when the derivative is already gone is unrecoverable.
    """
    from app.core import config
    from app.models.assets import ANALYSIS_PROXY, ORIGINAL

    if config.RETAIN_ORIGINAL_ALWAYS:
        return []

    now = datetime.now(timezone.utc)
    candidates = db.query(Video).filter(
        Video.status == vs.ANALYZED,
        Video.deleted_at.is_(None),
        Video.original_retained_until.isnot(None),
        Video.original_retained_until < now,
    ).all()

    storage = get_storage()
    actions: list[dict] = []
    for video in candidates:
        original = db.query(VideoAsset).filter_by(
            video_id=video.id, asset_type=ORIGINAL, deleted_at=None).first()
        proxy = db.query(VideoAsset).filter_by(
            video_id=video.id, asset_type=ANALYSIS_PROXY, deleted_at=None).first()
        if original is None or proxy is None:
            continue
        if storage.stat(proxy.storage_bucket, proxy.storage_path) is None:
            log(logger, logging.WARNING, "retention skipped: analysis proxy missing",
                video_id=video.id)
            continue

        action = {"video_id": video.id, "asset_id": original.id,
                  "bucket": original.storage_bucket, "key": original.storage_path,
                  "size_bytes": original.size_bytes}
        if not dry_run:
            storage.delete(original.storage_bucket, [original.storage_path])
            usage_service.add_asset_bytes(db, original.owner_user_id, ORIGINAL,
                                          -(original.size_bytes or 0))
            original.deleted_at = now
            action["deleted"] = True
        actions.append(action)

    if not dry_run:
        db.commit()
    return actions
