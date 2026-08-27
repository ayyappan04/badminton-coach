"""Durable job system: claim, lease, heartbeat, idempotency, recovery.

These are the properties the queue does NOT give us and the application has to
guarantee itself. Queues deliver at least once; workers get SIGKILLed; two
containers poll the same queue. Each test below corresponds to one of those
realities.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.db.session import SessionLocal
from app.jobs.base import JobMessage, OP_ANALYZE, OP_INGEST
from app.jobs.handlers import claim_run, requeue_stalled
from app.models.runs import AnalysisRun, CLAIMED, FAILED, PENDING, RUNNING, SUCCEEDED
from app.models.video import Video
from app.services import upload_service


@pytest.fixture()
def queued_video(client, user_a, upload_flow, tiny_mp4, deferred_jobs):
    """A video that has completed upload and has a pending analysis run.

    `deferred_jobs` keeps the run PENDING so these tests own the lifecycle.
    """
    video_id, _ = upload_flow.full(user_a, tiny_mp4.read_bytes())
    upload_flow.complete(user_a, video_id)
    with SessionLocal() as db:
        run = db.query(AnalysisRun).filter_by(video_id=video_id).first()
        assert run is not None
        return video_id, run.id


# --- idempotency ------------------------------------------------------------

def test_idempotency_key_is_stable_and_discriminating():
    a = JobMessage(operation=OP_INGEST, video_id="v1", analysis_run_id="r1",
                   pipeline_version="2.0.0")
    b = JobMessage(operation=OP_INGEST, video_id="v1", analysis_run_id="r1",
                   pipeline_version="2.0.0")
    assert a.idempotency_key == b.idempotency_key, "duplicate delivery must resolve identically"

    for changed in [
        JobMessage(operation=OP_ANALYZE, video_id="v1", analysis_run_id="r1", pipeline_version="2.0.0"),
        JobMessage(operation=OP_INGEST, video_id="v2", analysis_run_id="r1", pipeline_version="2.0.0"),
        JobMessage(operation=OP_INGEST, video_id="v1", analysis_run_id="r2", pipeline_version="2.0.0"),
        JobMessage(operation=OP_INGEST, video_id="v1", analysis_run_id="r1", pipeline_version="2.1.0"),
    ]:
        assert changed.idempotency_key != a.idempotency_key


def test_message_survives_a_serialization_round_trip():
    original = JobMessage(operation=OP_INGEST, video_id="v", analysis_run_id="r",
                          pipeline_version="2.0.0", payload={"reason": "retry"})
    restored = JobMessage.from_dict(original.to_dict(), receipt="7", read_count=2)
    assert restored.idempotency_key == original.idempotency_key
    assert restored.payload == {"reason": "retry"}
    assert restored.receipt == "7" and restored.read_count == 2


# --- claiming ---------------------------------------------------------------

def test_only_one_worker_can_claim_a_run(queued_video):
    """Two containers polling the same queue must not both start the pipeline."""
    _, run_id = queued_video
    with SessionLocal() as db:
        first = claim_run(db, run_id, "worker-a")
        assert first is not None
        assert first.status == CLAIMED and first.worker_id == "worker-a"

    with SessionLocal() as db:
        second = claim_run(db, run_id, "worker-b")
        assert second is None, "a second worker claimed a live lease"

    with SessionLocal() as db:
        assert db.get(AnalysisRun, run_id).worker_id == "worker-a"


def test_claim_sets_a_lease_with_an_expiry(queued_video):
    _, run_id = queued_video
    with SessionLocal() as db:
        run = claim_run(db, run_id, "worker-a")
        assert run.claimed_at is not None
        assert run.heartbeat_at is not None
        assert run.lease_expires_at is not None
        assert run.lease_expires_at > run.claimed_at


def test_expired_lease_is_reclaimable(queued_video):
    """A worker that was SIGKILLed must not park the video forever."""
    _, run_id = queued_video
    with SessionLocal() as db:
        claim_run(db, run_id, "dead-worker")
        run = db.get(AnalysisRun, run_id)
        run.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.commit()

    with SessionLocal() as db:
        reclaimed = claim_run(db, run_id, "fresh-worker")
        assert reclaimed is not None
        assert reclaimed.worker_id == "fresh-worker"


def test_succeeded_run_is_not_reclaimable(queued_video):
    _, run_id = queued_video
    with SessionLocal() as db:
        run = db.get(AnalysisRun, run_id)
        run.status = SUCCEEDED
        db.commit()
    with SessionLocal() as db:
        assert claim_run(db, run_id, "worker-a") is None


# --- stale recovery ---------------------------------------------------------

def test_requeue_stalled_returns_the_video_to_the_queue(queued_video):
    video_id, run_id = queued_video
    with SessionLocal() as db:
        claim_run(db, run_id, "dead-worker")
        run = db.get(AnalysisRun, run_id)
        run.status = RUNNING
        run.stage = "estimating_pose"
        run.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=30)
        db.commit()

    with SessionLocal() as db:
        assert requeue_stalled(db) == 1
        run = db.get(AnalysisRun, run_id)
        assert run.status == PENDING
        assert run.attempt == 2
        assert run.worker_id is None
        # The video must be back in a waiting state, not stuck mid-processing.
        assert db.get(Video, video_id).status == "queued"


def test_stalled_run_that_exhausted_attempts_fails_cleanly(queued_video):
    """Retrying forever is not recovery. After max attempts the user gets a
    clear terminal state instead of a video that never resolves."""
    video_id, run_id = queued_video
    with SessionLocal() as db:
        claim_run(db, run_id, "dead-worker")
        run = db.get(AnalysisRun, run_id)
        run.status = RUNNING
        run.attempt = run.max_attempts
        run.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=30)
        db.commit()

    with SessionLocal() as db:
        assert requeue_stalled(db) == 0
        run = db.get(AnalysisRun, run_id)
        assert run.status == FAILED
        assert run.error_code == "worker_lost"
        assert run.retryable is False

        video = db.get(Video, video_id)
        assert video.status == "failed"
        assert video.processing_error, "a failed video must carry a user-facing message"
        # The internal detail must never be the user-facing message.
        assert "Traceback" not in (video.processing_error or "")


def test_requeue_ignores_runs_for_deleted_videos(queued_video):
    video_id, run_id = queued_video
    with SessionLocal() as db:
        claim_run(db, run_id, "dead-worker")
        run = db.get(AnalysisRun, run_id)
        run.status = RUNNING
        run.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=30)
        db.get(Video, video_id).deleted_at = datetime.now(timezone.utc)
        db.commit()

    with SessionLocal() as db:
        assert requeue_stalled(db) == 0
        assert db.get(AnalysisRun, run_id).status == "cancelled"


# --- heartbeat --------------------------------------------------------------

def test_heartbeat_extends_the_lease(queued_video):
    """Analysis of a long match outlives any sane fixed lease."""
    from app.jobs.handlers import Heartbeat

    _, run_id = queued_video
    with SessionLocal() as db:
        claim_run(db, run_id, "worker-a")
        run = db.get(AnalysisRun, run_id)
        run.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=5)
        db.commit()
        before = run.lease_expires_at

    hb = Heartbeat(run_id, interval_s=0.2)
    with hb:
        import time
        time.sleep(0.7)

    with SessionLocal() as db:
        after = db.get(AnalysisRun, run_id).lease_expires_at
    assert after > before, "heartbeat did not extend the lease"


# --- reprocessing -----------------------------------------------------------

def test_reprocess_creates_a_new_run_and_keeps_the_old_one(client, user_a, queued_video):
    """Pipeline versions change. Re-analyzing must not rewrite history."""
    video_id, first_run = queued_video
    with SessionLocal() as db:
        run = db.get(AnalysisRun, first_run)
        run.status = SUCCEEDED
        run.is_current = True
        db.commit()

    r = client.post(f"/api/v1/videos/{video_id}/reprocess", headers=user_a["headers"])
    assert r.status_code == 200
    assert r.json()["started"] is True
    assert r.json()["analysis_run_id"] != first_run

    runs = client.get(f"/api/v1/videos/{video_id}/runs", headers=user_a["headers"]).json()
    assert len(runs) == 2, "the previous run was destroyed"
    assert any(x["id"] == first_run for x in runs)


def test_reprocess_while_a_run_is_active_is_a_no_op(client, user_a, queued_video):
    """Double-clicking Retry must not queue two pipelines."""
    video_id, run_id = queued_video
    r = client.post(f"/api/v1/videos/{video_id}/reprocess", headers=user_a["headers"])
    assert r.status_code == 200
    assert r.json()["started"] is False
    assert r.json()["analysis_run_id"] == run_id


def test_reprocess_is_denied_to_another_user(client, user_b, queued_video):
    video_id, _ = queued_video
    assert client.post(f"/api/v1/videos/{video_id}/reprocess",
                       headers=user_b["headers"]).status_code == 404


def test_run_records_its_configuration_as_provenance(queued_video):
    """A number must be traceable to the settings that produced it."""
    _, run_id = queued_video
    with SessionLocal() as db:
        run = db.get(AnalysisRun, run_id)
        cfg = run.configuration or {}
        assert run.pipeline_version
        assert "frame_sample_fps" in cfg
        assert "media_transform_version" in cfg
        assert "analysis_profile" in cfg


# --- dispatcher -------------------------------------------------------------

def test_local_dispatcher_roundtrip():
    from app.jobs.local import LocalJobDispatcher

    d = LocalJobDispatcher(eager=False)
    msg = JobMessage(operation=OP_INGEST, video_id="v", analysis_run_id="r",
                     pipeline_version="2.0.0")
    d.enqueue(msg)
    assert d.depth() == 1

    received = d.receive(max_messages=1)
    assert len(received) == 1
    assert received[0].video_id == "v"
    assert d.depth() == 0

    d.nack(received[0])
    assert d.depth() == 1, "a nacked message must become visible again"


def test_dispatcher_selection_follows_config(monkeypatch):
    from app.core import config
    from app.jobs import get_dispatcher, reset_dispatcher_cache

    reset_dispatcher_cache()
    monkeypatch.setattr(config, "JOB_BACKEND", "pgmq")
    assert get_dispatcher().backend == "pgmq"
    assert get_dispatcher().durable is True

    reset_dispatcher_cache()
    monkeypatch.setattr(config, "JOB_BACKEND", "local")
    assert get_dispatcher().backend == "local"
    reset_dispatcher_cache()
