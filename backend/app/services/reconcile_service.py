"""Storage reconciliation.

Two systems, no shared transaction, therefore drift. This compares what
`video_assets` claims against what the buckets actually hold and classifies
every disagreement.

It reports by default and never deletes unless explicitly told to. An
automated deleter that is wrong once destroys a user's match footage; a
reporter that is wrong once produces a line of output.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.core import config
from app.core.observability import log
from app.models.assets import VideoAsset
from app.models.video import Video
from app.services import usage_service
from app.storage import get_storage

logger = logging.getLogger("app.reconcile")


@dataclass
class ReconcileReport:
    scanned_assets: int = 0
    scanned_objects: int = 0
    missing_objects: List[dict] = field(default_factory=list)   # row says yes, bucket says no
    orphaned_objects: List[dict] = field(default_factory=list)  # bucket says yes, row says no
    size_mismatches: List[dict] = field(default_factory=list)
    usage_corrections: List[dict] = field(default_factory=list)
    deleted_objects: int = 0
    dry_run: bool = True

    def as_dict(self) -> dict:
        return {
            "dry_run": self.dry_run,
            "scanned_assets": self.scanned_assets,
            "scanned_objects": self.scanned_objects,
            "missing_objects": self.missing_objects,
            "orphaned_objects": self.orphaned_objects,
            "size_mismatches": self.size_mismatches,
            "usage_corrections": self.usage_corrections,
            "deleted_objects": self.deleted_objects,
            "healthy": not (self.missing_objects or self.orphaned_objects
                            or self.size_mismatches),
        }


def reconcile(db: Session, *, user_id: Optional[str] = None, dry_run: bool = True,
              delete_orphans: bool = False) -> ReconcileReport:
    report = ReconcileReport(dry_run=dry_run)
    storage = get_storage()

    asset_q = db.query(VideoAsset).filter(VideoAsset.deleted_at.is_(None))
    if user_id:
        asset_q = asset_q.filter(VideoAsset.owner_user_id == user_id)
    assets = asset_q.all()
    report.scanned_assets = len(assets)

    known: Dict[str, set] = {}
    for asset in assets:
        known.setdefault(asset.storage_bucket, set()).add(asset.storage_path)
        stat = storage.stat(asset.storage_bucket, asset.storage_path)
        if stat is None:
            report.missing_objects.append({
                "asset_id": asset.id, "video_id": asset.video_id,
                "asset_type": asset.asset_type, "bucket": asset.storage_bucket,
                "key": asset.storage_path, "recorded_bytes": asset.size_bytes,
            })
            continue
        if stat.size_bytes != (asset.size_bytes or 0):
            report.size_mismatches.append({
                "asset_id": asset.id, "bucket": asset.storage_bucket,
                "key": asset.storage_path, "recorded_bytes": asset.size_bytes,
                "actual_bytes": stat.size_bytes,
            })
            if not dry_run:
                asset.size_bytes = stat.size_bytes

    # Objects with no live asset row. Scoped to one user's prefix when a user
    # is given, so this stays affordable to run.
    prefixes: List[tuple] = []
    for bucket in (config.BUCKET_ORIGINALS, config.BUCKET_DERIVED):
        prefixes.append((bucket, f"{user_id}/" if user_id else ""))

    for bucket, prefix in prefixes:
        try:
            objects = storage.list_prefix(bucket, prefix)
        except Exception:  # noqa: BLE001
            log(logger, logging.WARNING, "listing failed", bucket=bucket)
            continue
        report.scanned_objects += len(objects)
        for obj in objects:
            if obj.key in known.get(bucket, set()):
                continue
            report.orphaned_objects.append({
                "bucket": bucket, "key": obj.key, "size_bytes": obj.size_bytes,
                "owner_user_id": obj.key.split("/", 1)[0],
            })

    if delete_orphans and not dry_run and report.orphaned_objects:
        by_bucket: Dict[str, List[str]] = {}
        for entry in report.orphaned_objects:
            by_bucket.setdefault(entry["bucket"], []).append(entry["key"])
        for bucket, keys in by_bucket.items():
            report.deleted_objects += storage.delete(bucket, keys)

    # Usage counters vs. the asset table.
    user_ids = [user_id] if user_id else sorted({a.owner_user_id for a in assets})
    for uid in user_ids:
        if not uid:
            continue
        before = usage_service.snapshot(db, uid)
        row = usage_service.recalculate(db, uid)
        if row.total_bytes != before["total_bytes"]:
            report.usage_corrections.append({
                "user_id": uid, "was_bytes": before["total_bytes"],
                "now_bytes": row.total_bytes,
            })
        if dry_run:
            db.rollback()

    if not dry_run:
        db.commit()

    log(logger, logging.INFO, "reconciliation complete", **{
        k: v for k, v in report.as_dict().items() if isinstance(v, (int, bool))
    })
    return report


def find_stale_derived(db: Session) -> List[dict]:
    """Derived assets whose transform version no longer matches current
    configuration. Reproducible, so they can be regenerated on demand."""
    from app.storage.paths import MEDIA_TRANSFORM_VERSION
    from app.models.assets import REPRODUCIBLE

    rows = db.query(VideoAsset).filter(
        VideoAsset.deleted_at.is_(None),
        VideoAsset.asset_type.in_(tuple(REPRODUCIBLE)),
        VideoAsset.transform_version.isnot(None),
        VideoAsset.transform_version != MEDIA_TRANSFORM_VERSION,
    ).all()
    return [{
        "asset_id": a.id, "video_id": a.video_id, "asset_type": a.asset_type,
        "transform_version": a.transform_version, "current": MEDIA_TRANSFORM_VERSION,
        "size_bytes": a.size_bytes,
    } for a in rows]


def find_stuck_videos(db: Session, older_than_minutes: int = 60) -> List[dict]:
    """Videos parked in an in-flight state with no live lease behind them."""
    from datetime import datetime, timedelta, timezone
    from app.models.runs import AnalysisRun
    from app.services import video_state as vs

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
    videos = db.query(Video).filter(
        Video.status.in_(tuple(vs.IN_FLIGHT)),
        Video.updated_at < cutoff,
        Video.deleted_at.is_(None),
    ).all()
    out = []
    for video in videos:
        run = db.query(AnalysisRun).filter_by(video_id=video.id).order_by(
            AnalysisRun.created_at.desc()).first()
        out.append({
            "video_id": video.id, "owner_user_id": video.owner_user_id,
            "status": video.status, "stage": video.stage,
            "updated_at": video.updated_at.isoformat() if video.updated_at else None,
            "run_id": run.id if run else None,
            "run_status": run.status if run else None,
            "lease_expires_at": run.lease_expires_at.isoformat()
                                if run and run.lease_expires_at else None,
            "attempt": run.attempt if run else None,
        })
    return out
