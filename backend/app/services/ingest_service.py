"""Media ingestion: the phase between "bytes arrived" and "the CV pipeline
may start".

    original in the bucket
        -> download to a per-run temp directory
        -> probe (ffprobe is the authority, not the browser)
        -> validate against production limits
        -> checksum
        -> normalize into an analysis proxy and a playback proxy
        -> poster + thumbnail
        -> upload derived assets, record them, account for the bytes

Idempotent by construction. If a run failed after normalization and is
retried, the existing analysis proxy is reused — the retry downloads a few
hundred megabytes instead of re-downloading and re-transcoding several
gigabytes.
"""
from __future__ import annotations

import logging
import shutil
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.core import config
from app.core.observability import NORMALIZATION_SECONDS, log, metrics
from app.media import normalize as media_normalize
from app.media.errors import MediaError, E_OBJECT_MISSING
from app.media.probe import MediaInfo, probe, validate
from app.models.assets import (
    ANALYSIS_PROXY, ORIGINAL, PLAYBACK_PROXY, POSTER, THUMBNAIL, VideoAsset,
)
from app.models.runs import AnalysisRun
from app.models.video import Video
from app.services import events, usage_service
from app.storage import get_storage, sha256_file
from app.storage.base import guess_content_type
from app.storage.paths import (
    MEDIA_TRANSFORM_VERSION, analysis_key, playback_key, poster_key, thumbnail_key,
)

logger = logging.getLogger("app.ingest")


class WorkDir:
    """A unique scratch directory per analysis run.

    Worker local disk is ephemeral by contract. Nothing here is permanent
    state, and the directory is removed even when the run raises — otherwise a
    worker that fails ten multi-gigabyte jobs fills its own disk and stops
    being a worker.
    """

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.path: Optional[Path] = None

    def __enter__(self) -> Path:
        self.path = Path(tempfile.mkdtemp(prefix=f"ss-{self.run_id[:8]}-"))
        return self.path

    def __exit__(self, *exc) -> None:
        if self.path:
            shutil.rmtree(self.path, ignore_errors=True)
            log(logger, logging.DEBUG, "workdir removed", path=str(self.path))


def _live_asset(db: Session, video_id: str, asset_type: str) -> Optional[VideoAsset]:
    return db.query(VideoAsset).filter_by(
        video_id=video_id, asset_type=asset_type, deleted_at=None).first()


def _is_fresh(asset: Optional[VideoAsset], source_checksum: Optional[str]) -> bool:
    """A derived asset is reusable only if the transform that made it and the
    bytes it was made from both still match."""
    if asset is None:
        return False
    if asset.transform_version != MEDIA_TRANSFORM_VERSION:
        return False
    if source_checksum and asset.source_checksum and asset.source_checksum != source_checksum:
        return False
    return True


def _record_asset(db: Session, video: Video, *, asset_type: str, bucket: str, key: str,
                  local: Path, info: Optional[MediaInfo] = None,
                  source_asset_id: Optional[str] = None,
                  source_checksum: Optional[str] = None,
                  extra: Optional[dict] = None) -> VideoAsset:
    size = local.stat().st_size
    mime = guess_content_type(local.suffix)
    existing = _live_asset(db, video.id, asset_type)
    if existing:
        usage_service.add_asset_bytes(db, video.owner_user_id, asset_type, -(existing.size_bytes or 0))
        asset = existing
    else:
        asset = VideoAsset(video_id=video.id, owner_user_id=video.owner_user_id,
                           asset_type=asset_type)
        db.add(asset)

    asset.storage_bucket = bucket
    asset.storage_path = key
    asset.mime_type = mime
    asset.size_bytes = size
    asset.transform_version = MEDIA_TRANSFORM_VERSION
    asset.source_asset_id = source_asset_id
    asset.source_checksum = source_checksum
    asset.extra = extra
    if info:
        asset.width = info.display_width
        asset.height = info.display_height
        asset.fps = info.fps
        asset.duration_seconds = info.duration_s
        asset.codec = info.video_codec
        asset.container = info.container
    db.flush()
    usage_service.add_asset_bytes(db, video.owner_user_id, asset_type, size)
    return asset


def ensure_media_assets(db: Session, video: Video, run: AnalysisRun, workdir: Path,
                        progress_cb=None) -> Tuple[Path, MediaInfo]:
    """Guarantee an analysis-ready local file exists, and return its path.

    Returns (local analysis proxy path, source MediaInfo).
    """
    storage = get_storage()

    def report(pct: int, stage: str):
        if progress_cb:
            progress_cb(pct, stage)

    # --- reuse path ------------------------------------------------------
    existing_analysis = _live_asset(db, video.id, ANALYSIS_PROXY)
    if _is_fresh(existing_analysis, video.checksum_sha256):
        local = workdir / "analysis.mp4"
        report(12, "fetching_prepared_video")
        storage.download_to(existing_analysis.storage_bucket, existing_analysis.storage_path, local)
        log(logger, logging.INFO, "reused existing analysis proxy",
            asset_id=existing_analysis.id, size_bytes=existing_analysis.size_bytes)
        events.record(db, video_id=video.id, analysis_run_id=run.id,
                      owner_user_id=video.owner_user_id, event_type=events.STAGE_COMPLETED,
                      stage="normalizing", message="reused existing analysis proxy")
        return local, probe(local)

    # --- full ingest -----------------------------------------------------
    original = _live_asset(db, video.id, ORIGINAL)
    bucket = original.storage_bucket if original else video.storage_bucket
    key = original.storage_path if original else video.storage_key
    if not bucket or not key:
        raise MediaError(E_OBJECT_MISSING, "video has no original asset recorded")

    report(6, "fetching_video")
    events.record(db, video_id=video.id, analysis_run_id=run.id,
                  owner_user_id=video.owner_user_id, event_type=events.STAGE_STARTED,
                  stage="validating")

    src = workdir / f"original{Path(key).suffix or '.mp4'}"
    started = time.monotonic()
    downloaded = storage.download_to(bucket, key, src)
    log(logger, logging.INFO, "original downloaded", bytes=downloaded,
        seconds=round(time.monotonic() - started, 2))

    report(10, "checking_video")
    info = probe(src)
    validate(info, declared_size=video.source_size_bytes)

    checksum = sha256_file(src)
    video.checksum_sha256 = checksum
    video.source_container = info.container
    video.source_video_codec = info.video_codec
    video.source_audio_codec = info.audio_codec or None
    video.source_rotation = info.rotation
    video.source_bitrate = info.bitrate or None
    video.source_size_bytes = info.size_bytes or video.source_size_bytes
    video.duration_seconds = info.duration_s
    video.fps = info.fps
    video.resolution_w = info.display_width
    video.resolution_h = info.display_height
    if original and not original.checksum_sha256:
        original.checksum_sha256 = checksum
        original.duration_seconds = info.duration_s
        original.width = info.display_width
        original.height = info.display_height
        original.fps = info.fps
        original.codec = info.video_codec
        original.container = info.container
    if not video.original_retained_until:
        video.original_retained_until = datetime.now(timezone.utc) + timedelta(
            days=config.ORIGINAL_RETENTION_DAYS)
    db.commit()

    events.record(db, video_id=video.id, analysis_run_id=run.id,
                  owner_user_id=video.owner_user_id, event_type=events.STAGE_COMPLETED,
                  stage="validating", message=f"{info.display_width}x{info.display_height} "
                                              f"{info.fps:.2f}fps {info.video_codec}")

    # --- normalize -------------------------------------------------------
    report(14, "optimizing_video")
    events.record(db, video_id=video.id, analysis_run_id=run.id,
                  owner_user_id=video.owner_user_id, event_type=events.STAGE_STARTED,
                  stage="normalizing")

    analysis_local = workdir / "analysis.mp4"
    with metrics.timed(NORMALIZATION_SECONDS, profile="analysis"):
        analysis_info, analysis_plan = media_normalize.make_analysis_proxy(info, src, analysis_local)

    playback_local = workdir / "playback.mp4"
    with metrics.timed(NORMALIZATION_SECONDS, profile="playback"):
        playback_info, playback_plan = media_normalize.make_playback_proxy(info, src, playback_local)

    poster_local = workdir / "poster.jpg"
    thumb_local = workdir / "thumbnail.jpg"
    try:
        media_normalize.make_poster_and_thumbnail(info, src, poster_local, thumb_local)
    except MediaError as exc:
        # A missing thumbnail degrades the match library. It is not a reason to
        # refuse to analyze a match the user already uploaded.
        log(logger, logging.WARNING, "still capture failed", code=exc.code, detail=exc.detail[:200])

    # --- publish ---------------------------------------------------------
    report(20, "storing_prepared_video")
    owner = video.owner_user_id
    derived_bucket = config.BUCKET_DERIVED
    source_asset_id = original.id if original else None

    a_key = analysis_key(owner, video.id)
    storage.upload_file(derived_bucket, a_key, analysis_local, "video/mp4")
    _record_asset(db, video, asset_type=ANALYSIS_PROXY, bucket=derived_bucket, key=a_key,
                  local=analysis_local, info=analysis_info, source_asset_id=source_asset_id,
                  source_checksum=checksum, extra={"plan": analysis_plan.as_dict()})

    p_key = playback_key(owner, video.id)
    storage.upload_file(derived_bucket, p_key, playback_local, "video/mp4")
    _record_asset(db, video, asset_type=PLAYBACK_PROXY, bucket=derived_bucket, key=p_key,
                  local=playback_local, info=playback_info, source_asset_id=source_asset_id,
                  source_checksum=checksum, extra={"plan": playback_plan.as_dict()})

    for local, key_fn, asset_type in (
        (poster_local, poster_key, POSTER),
        (thumb_local, thumbnail_key, THUMBNAIL),
    ):
        if local.exists() and local.stat().st_size > 0:
            k = key_fn(owner, video.id)
            storage.upload_file(derived_bucket, k, local, "image/jpeg")
            _record_asset(db, video, asset_type=asset_type, bucket=derived_bucket, key=k,
                          local=local, source_asset_id=source_asset_id, source_checksum=checksum)

    run.analysis_asset_id = (_live_asset(db, video.id, ANALYSIS_PROXY) or VideoAsset()).id
    db.commit()

    events.record(db, video_id=video.id, analysis_run_id=run.id,
                  owner_user_id=video.owner_user_id, event_type=events.STAGE_COMPLETED,
                  stage="normalizing", message=analysis_plan.reason,
                  analysis_bytes=analysis_local.stat().st_size,
                  playback_bytes=playback_local.stat().st_size)

    log(logger, logging.INFO, "media ingest complete",
        analysis_bytes=analysis_local.stat().st_size,
        playback_bytes=playback_local.stat().st_size,
        passthrough=analysis_plan.passthrough)

    return analysis_local, info
