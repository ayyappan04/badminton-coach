"""What a worker actually does with a message.

Three properties this module has to guarantee, because the queue guarantees
none of them:

* **At-most-once effect.** Queues deliver at least once. A duplicate delivery
  must not start a second pipeline over the same footage, so work begins only
  after an atomic compare-and-set on the run row wins.
* **No permanent `processing`.** A worker that is SIGKILLed mid-analysis holds
  a lease that expires. `requeue_stalled` reclaims it. A video is never stuck
  because a machine went away.
* **Failures that say something.** Every terminal failure records a stage, a
  machine-readable code, a safe user sentence, the internal detail, and
  whether retrying could possibly help.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.core import config
from app.core.observability import (
    ANALYSIS_SECONDS, JOBS_RETRIED, PROCESSING_FAILURES, QUEUE_WAIT_SECONDS,
    STALE_LEASES_RECLAIMED, correlate, log, metrics, worker_identity,
)
from app.db.session import SessionLocal
from app.jobs.base import JobMessage, OP_ANALYZE, OP_CLEANUP, OP_INGEST
from app.media.errors import MediaError, E_INTERNAL, E_PIPELINE_FAILED, USER_MESSAGE
from app.models.runs import (
    AnalysisRun, CANCELLED, CLAIMED, FAILED, PENDING, RUNNING, SUCCEEDED,
)
from app.models.video import Video
from app.services import events, ingest_service, video_state as vs

logger = logging.getLogger("app.jobs.handlers")


class JobOutcome:
    ACK = "ack"                # done; remove the message
    RETRY = "retry"            # transient; make visible again after a delay
    DEAD_LETTER = "dead"       # poisoned; park it for a human


# ---------------------------------------------------------------------------
# Lease management
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def claim_run(db: Session, run_id: str, worker_id: str) -> Optional[AnalysisRun]:
    """Atomically take ownership of a run.

    One UPDATE with the guard in its WHERE clause, so two workers racing on the
    same message cannot both come away believing they own it. Returning zero
    rows is the normal, expected answer for the loser — not an error.
    """
    now = _now()
    lease_until = now + timedelta(seconds=config.JOB_LEASE_S)
    updated = (
        db.query(AnalysisRun)
        .filter(
            AnalysisRun.id == run_id,
            or_(
                AnalysisRun.status == PENDING,
                # Reclaimable: previously claimed, but the holder stopped
                # heartbeating before the lease ran out.
                and_(AnalysisRun.status.in_((CLAIMED, RUNNING)),
                     AnalysisRun.lease_expires_at.isnot(None),
                     AnalysisRun.lease_expires_at < now),
            ),
        )
        .update(
            {
                AnalysisRun.status: CLAIMED,
                AnalysisRun.worker_id: worker_id,
                AnalysisRun.claimed_at: now,
                AnalysisRun.heartbeat_at: now,
                AnalysisRun.lease_expires_at: lease_until,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    if not updated:
        return None
    return db.get(AnalysisRun, run_id)


class Heartbeat:
    """Extends the lease on a background thread while a long stage runs.

    Analysis of a full match takes minutes. Without a heartbeat the lease
    either has to be longer than the worst case — which delays every genuine
    crash recovery by that much — or it expires mid-run and a second worker
    starts duplicating the work.
    """

    def __init__(self, run_id: str, interval_s: Optional[int] = None):
        self.run_id = run_id
        self.interval = interval_s or config.JOB_HEARTBEAT_S
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _beat(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                with SessionLocal() as db:
                    now = _now()
                    db.query(AnalysisRun).filter(AnalysisRun.id == self.run_id).update(
                        {
                            AnalysisRun.heartbeat_at: now,
                            AnalysisRun.lease_expires_at: now + timedelta(seconds=config.JOB_LEASE_S),
                        },
                        synchronize_session=False,
                    )
                    db.commit()
            except Exception:  # noqa: BLE001 — a missed beat is survivable; a dead thread is not
                logger.warning("heartbeat failed for run %s", self.run_id, exc_info=True)

    def __enter__(self) -> "Heartbeat":
        self._thread = threading.Thread(target=self._beat, name=f"hb-{self.run_id[:8]}", daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)


def requeue_stalled(db: Session, dispatcher=None) -> int:
    """Reclaim runs whose worker died. Safe to run on a schedule."""
    from app.jobs import get_dispatcher
    dispatcher = dispatcher or get_dispatcher()
    now = _now()
    stalled = (
        db.query(AnalysisRun)
        .filter(
            AnalysisRun.status.in_((CLAIMED, RUNNING)),
            AnalysisRun.lease_expires_at.isnot(None),
            AnalysisRun.lease_expires_at < now,
        )
        .all()
    )
    requeued = 0
    for run in stalled:
        video = db.get(Video, run.video_id)
        if video is None or video.deleted_at is not None:
            run.status = CANCELLED
            continue
        if run.attempt >= run.max_attempts:
            _fail_run(db, run, video, code="worker_lost",
                      message="Analysis was interrupted too many times. Please try again.",
                      detail=f"lease expired {run.attempt} times", stage=run.stage or "unknown",
                      retryable=False)
            continue

        run.status = PENDING
        run.attempt += 1
        run.worker_id = None
        run.claimed_at = None
        run.lease_expires_at = None
        vs.advance(video, vs.QUEUED, stage="queued", strict=False)
        events.record(db, video_id=video.id, analysis_run_id=run.id,
                      owner_user_id=video.owner_user_id, event_type=events.LEASE_RECLAIMED,
                      stage=run.stage, message=f"lease expired; retry {run.attempt}",
                      commit=False)
        dispatcher.enqueue(JobMessage(
            operation=OP_INGEST, video_id=video.id, analysis_run_id=run.id,
            pipeline_version=run.pipeline_version,
        ))
        requeued += 1
        metrics.incr(STALE_LEASES_RECLAIMED)
    db.commit()
    if requeued:
        log(logger, logging.WARNING, "reclaimed stalled runs", count=requeued)
    return requeued


# ---------------------------------------------------------------------------
# Failure recording
# ---------------------------------------------------------------------------

def _fail_run(db: Session, run: AnalysisRun, video: Optional[Video], *, code: str,
              message: str, detail: str, stage: str, retryable: bool) -> None:
    run.status = FAILED
    run.error_code = code
    run.error_message = message          # safe, shown to the user
    run.error_detail = detail[:8000]     # internal, never leaves the server
    run.failed_stage = stage
    run.retryable = retryable
    run.completed_at = _now()
    if video is not None:
        video.processing_error = message
        video.processing_error_code = code
        video.processing_error_retryable = retryable
        video.failed_stage = stage
        vs.advance(video, vs.FAILED, strict=False)
    events.record(db, video_id=run.video_id, analysis_run_id=run.id,
                  owner_user_id=run.owner_user_id, event_type=events.FAILED,
                  stage=stage, message=message, worker_id=run.worker_id, commit=False,
                  error_code=code)
    db.commit()
    metrics.incr(PROCESSING_FAILURES, stage=stage)
    log(logger, logging.ERROR, "run failed", code=code, stage=stage,
        retryable=retryable, detail=detail[:500])


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def execute(message: JobMessage) -> str:
    """Handle one message. Returns a JobOutcome."""
    with correlate(video_id=message.video_id, analysis_run_id=message.analysis_run_id,
                   job_id=message.receipt):
        if message.operation in (OP_INGEST, OP_ANALYZE):
            return _ingest_and_analyze(message)
        if message.operation == OP_CLEANUP:
            return _cleanup(message)
        log(logger, logging.ERROR, "unknown operation", operation=message.operation)
        return JobOutcome.DEAD_LETTER


def _ingest_and_analyze(message: JobMessage) -> str:
    """Ingest and analysis in one job, deliberately.

    Splitting them would mean a second worker downloading the analysis proxy
    again. For a multi-gigabyte match that is a real cost for no durability
    gain: the lease already covers a long job, and a crash between the two
    phases resumes cheaply because ingest skips work already committed.
    """
    worker_id = worker_identity()
    db = SessionLocal()
    try:
        video = db.get(Video, message.video_id)
        if video is None or video.deleted_at is not None:
            log(logger, logging.INFO, "video gone; dropping message")
            return JobOutcome.ACK
        if video.status in (vs.CANCELLED, vs.DELETED):
            return JobOutcome.ACK

        run = db.get(AnalysisRun, message.analysis_run_id) if message.analysis_run_id else None
        if run is None:
            log(logger, logging.ERROR, "message references no analysis run")
            return JobOutcome.DEAD_LETTER

        # Idempotency gate. A duplicate delivery of already-finished work is
        # normal queue behaviour, not an error worth retrying.
        if run.status == SUCCEEDED:
            log(logger, logging.INFO, "run already succeeded; dropping duplicate")
            return JobOutcome.ACK
        if run.status == CANCELLED:
            return JobOutcome.ACK

        claimed = claim_run(db, run.id, worker_id)
        if claimed is None:
            # Another worker holds a live lease. Come back later rather than
            # racing it.
            log(logger, logging.INFO, "run not claimable; another worker holds the lease")
            return JobOutcome.RETRY
        run = claimed

        if run.created_at:
            waited = (_now() - run.created_at.replace(tzinfo=timezone.utc)).total_seconds()
            metrics.observe(QUEUE_WAIT_SECONDS, max(0.0, waited))

        events.record(db, video_id=video.id, analysis_run_id=run.id,
                      owner_user_id=video.owner_user_id, event_type=events.CLAIMED,
                      worker_id=worker_id)

        run.status = RUNNING
        run.started_at = run.started_at or _now()
        vs.advance(video, vs.NORMALIZING, stage="validating", progress_pct=5, strict=False)
        db.commit()

        with Heartbeat(run.id), ingest_service.WorkDir(run.id) as workdir:
            def progress(pct: int, stage: str):
                run.progress_pct = pct
                run.stage = stage
                db.commit()

            try:
                source, _info = ingest_service.ensure_media_assets(
                    db, video, run, workdir, progress_cb=progress)
            except MediaError as exc:
                _fail_run(db, run, video, code=exc.code, message=exc.user_message,
                          detail=f"{exc.detail}", stage=exc.stage or "normalizing",
                          retryable=exc.retryable)
                return JobOutcome.RETRY if exc.retryable and run.attempt < run.max_attempts else JobOutcome.ACK

            vs.advance(video, vs.PROCESSING, stage="analyzing", progress_pct=25, strict=False)
            events.record(db, video_id=video.id, analysis_run_id=run.id,
                          owner_user_id=video.owner_user_id, event_type=events.STAGE_STARTED,
                          stage="analyzing", worker_id=worker_id)
            db.commit()

            started = time.monotonic()
            try:
                from app.services import analysis_service
                analysis_service.process_video(
                    video.id, source_path=str(source), run=run, workdir=workdir,
                    progress_cb=progress,
                )
            except Exception as exc:  # noqa: BLE001
                detail = traceback.format_exc()
                _fail_run(db, run, video, code=E_PIPELINE_FAILED,
                          message=USER_MESSAGE[E_PIPELINE_FAILED],
                          detail=detail, stage=run.stage or "analyzing", retryable=True)
                if run.attempt < run.max_attempts:
                    metrics.incr(JOBS_RETRIED)
                    return JobOutcome.RETRY
                return JobOutcome.ACK
            finally:
                metrics.observe(ANALYSIS_SECONDS, time.monotonic() - started)

        db.expire_all()
        video = db.get(Video, message.video_id)
        run = db.get(AnalysisRun, run.id)

        run.status = SUCCEEDED
        run.completed_at = _now()
        run.progress_pct = 100
        run.metrics = {
            "duration_seconds": round(time.monotonic() - started, 2),
            "analysis_confidence": video.analysis_confidence,
            "quality_score": video.quality_score,
        }
        _mark_current(db, run)
        video.current_analysis_run_id = run.id
        video.pipeline_version = run.pipeline_version
        events.record(db, video_id=video.id, analysis_run_id=run.id,
                      owner_user_id=video.owner_user_id, event_type=events.COMPLETED,
                      progress_pct=100, worker_id=worker_id, commit=False,
                      status=video.status)
        db.commit()
        log(logger, logging.INFO, "run succeeded", status=video.status)
        return JobOutcome.ACK

    except Exception:  # noqa: BLE001 — never let a handler bug kill the worker loop
        logger.exception("unhandled error in job handler")
        try:
            db.rollback()
            run = db.get(AnalysisRun, message.analysis_run_id) if message.analysis_run_id else None
            video = db.get(Video, message.video_id)
            if run is not None:
                _fail_run(db, run, video, code=E_INTERNAL, message=USER_MESSAGE[E_INTERNAL],
                          detail=traceback.format_exc(), stage=run.stage or "unknown",
                          retryable=True)
        except Exception:  # noqa: BLE001
            logger.exception("could not record job failure")
        return JobOutcome.RETRY
    finally:
        db.close()


def _mark_current(db: Session, run: AnalysisRun) -> None:
    """Exactly one run per video is the current one. Demote the others first
    so there is never a moment with two."""
    db.query(AnalysisRun).filter(
        AnalysisRun.video_id == run.video_id, AnalysisRun.id != run.id,
        AnalysisRun.is_current.is_(True),
    ).update({AnalysisRun.is_current: False}, synchronize_session=False)
    run.is_current = True


def _cleanup(message: JobMessage) -> str:
    """Delete the objects belonging to a tombstoned video."""
    from app.services import deletion_service
    db = SessionLocal()
    try:
        removed = deletion_service.purge_video_objects(db, message.video_id)
        log(logger, logging.INFO, "cleanup complete", objects_removed=removed)
        return JobOutcome.ACK
    except Exception:  # noqa: BLE001
        logger.exception("cleanup failed")
        return JobOutcome.RETRY
    finally:
        db.close()
