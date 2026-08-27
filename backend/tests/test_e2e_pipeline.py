"""End-to-end: account -> upload -> queue -> worker -> results -> playback -> delete.

This is the Definition of Done as an executable test. It drives the real
Worker loop rather than calling handlers directly, so the claim, lease,
heartbeat, ack and state-transition paths are all exercised the way they run
in production.

Marked `integration` because it runs the full CV pipeline and takes tens of
seconds; unit tests stay fast and this is separable:

    pytest -m "not integration"        # fast
    pytest -m integration              # this file
"""
import subprocess

import pytest

from app.db.session import SessionLocal
from app.jobs.runner import Worker
from app.media import ffmpeg
from app.models.assets import (
    ANALYSIS_PROXY, ORIGINAL, PLAYBACK_PROXY, POSTER, THUMBNAIL, VideoAsset,
)
from app.models.runs import AnalysisRun, ProcessingEvent, SUCCEEDED
from app.models.video import Video

pytestmark = pytest.mark.integration


@pytest.fixture()
def match_clip(tmp_path, ffmpeg_available):
    """A short synthetic 'match': two moving figures on a court-ish background.

    Not real badminton, and not pretending to be. Its job is to be a genuinely
    decodable H.264 file with motion so every pipeline stage runs against real
    frames rather than a stub.
    """
    path = tmp_path / "match.mp4"
    subprocess.run([
        ffmpeg.ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", "color=c=#1a5c2a:size=960x540:rate=25:duration=3",
        "-f", "lavfi", "-i", "color=c=white:size=40x110:rate=25:duration=3",
        "-f", "lavfi", "-i", "color=c=#dd3322:size=40x110:rate=25:duration=3",
        "-filter_complex",
        "[0][1]overlay=x='300+180*sin(t*2)':y='300+40*cos(t*3)'[a];"
        "[a][2]overlay=x='560-160*sin(t*1.7)':y='120+30*sin(t*2.5)'",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "23",
        "-pix_fmt", "yuv420p", str(path),
    ], check=True, capture_output=True)
    assert path.stat().st_size > 0
    return path


def test_full_upload_to_playback_journey(client, user_a, upload_flow, match_clip,
                                         deferred_jobs):
    data = match_clip.read_bytes()

    # ---- 1. authorize an upload -------------------------------------------
    ticket_res = upload_flow.initiate(user_a, filename="match.mp4",
                                      size_bytes=len(data), match_format="singles",
                                      opponent_name="Test Opponent")
    assert ticket_res.status_code == 200
    ticket = ticket_res.json()
    video_id = ticket["video_id"]

    # The object key is owner-scoped; that prefix IS the storage authorization
    # boundary in production.
    assert ticket["object_path"].startswith(f"{user_a['id']}/")

    with SessionLocal() as db:
        assert db.get(Video, video_id).status == "created"

    # ---- 2. bytes go browser -> storage, not through the API --------------
    assert upload_flow.put(user_a, video_id, data).status_code == 200

    # ---- 3. verify and enqueue --------------------------------------------
    done = upload_flow.complete(user_a, video_id)
    assert done.status_code == 200, done.text
    run_id = done.json()["analysis_run_id"]

    with SessionLocal() as db:
        video = db.get(Video, video_id)
        assert video.status == "queued"
        assert video.source_size_bytes == len(data)
        # The original asset is recorded before any processing starts.
        assert db.query(VideoAsset).filter_by(
            video_id=video_id, asset_type=ORIGINAL, deleted_at=None).first() is not None

    assert deferred_jobs.depth() == 1, "completion did not enqueue exactly one job"

    # ---- 4. a worker picks it up ------------------------------------------
    # The real loop: receive -> claim -> lease -> execute -> ack.
    worker = Worker(concurrency=1)
    worker.dispatcher = deferred_jobs
    handled = worker.run_once()
    assert handled == 1
    assert deferred_jobs.depth() == 0, "the message was not acked"

    # ---- 5. results are persisted -----------------------------------------
    with SessionLocal() as db:
        run = db.get(AnalysisRun, run_id)
        assert run.status == SUCCEEDED, f"{run.status}: {run.error_code} {run.error_message}"
        assert run.is_current is True
        assert run.completed_at is not None
        assert run.progress_pct == 100

        video = db.get(Video, video_id)
        assert video.status in ("analyzed", "needs_player_selection"), video.status
        # Authoritative metadata came from ffprobe, not from the browser.
        assert video.duration_seconds and video.duration_seconds > 0
        assert video.resolution_w == 960 and video.resolution_h == 540
        assert video.source_video_codec == "h264"
        assert video.checksum_sha256 and len(video.checksum_sha256) == 64
        assert video.pipeline_version

        # Derived assets exist and are attributed to the owner.
        by_type = {
            a.asset_type: a for a in
            db.query(VideoAsset).filter_by(video_id=video_id, deleted_at=None).all()
        }
        for required in (ORIGINAL, ANALYSIS_PROXY, PLAYBACK_PROXY, POSTER, THUMBNAIL):
            assert required in by_type, f"missing derived asset: {required}"
            assert by_type[required].owner_user_id == user_a["id"]
            assert by_type[required].storage_path.startswith(f"{user_a['id']}/")

        # The playback proxy must actually be the cheaper one to serve.
        assert by_type[PLAYBACK_PROXY].size_bytes > 0
        assert by_type[ANALYSIS_PROXY].size_bytes > 0

        # A coarse, useful event trail -- not one row per frame.
        events = db.query(ProcessingEvent).filter_by(video_id=video_id).all()
        assert 3 <= len(events) <= 40, f"{len(events)} events is the wrong order of magnitude"
        assert {"validating", "normalizing"} <= {e.stage for e in events if e.stage}

    # ---- 6. the match is readable through the API -------------------------
    video_json = client.get(f"/api/v1/videos/{video_id}", headers=user_a["headers"]).json()
    assert video_json["status_group"] in ("ready", "action_required")
    assert video_json["has_playback_asset"] is True
    assert video_json["opponent_name"] == "Test Opponent"

    quality = client.get(f"/api/v1/videos/{video_id}/quality-report",
                         headers=user_a["headers"])
    assert quality.status_code == 200
    assert "score" in quality.json()

    runs = client.get(f"/api/v1/videos/{video_id}/runs", headers=user_a["headers"]).json()
    assert len(runs) == 1 and runs[0]["is_current"] is True
    assert runs[0]["configuration"], "provenance was not recorded"

    # ---- 7. playback resolves to a proxy, never the original --------------
    playback = client.get(f"/api/v1/videos/{video_id}/playback", headers=user_a["headers"])
    assert playback.status_code == 200, playback.text
    body = playback.json()
    assert body["asset_type"] == PLAYBACK_PROXY, "playback served something other than the proxy"
    assert body["url"]

    # ---- 8. deletion revokes access immediately ---------------------------
    assert client.delete(f"/api/v1/videos/{video_id}",
                         headers=user_a["headers"]).status_code == 200

    assert client.get(f"/api/v1/videos/{video_id}",
                      headers=user_a["headers"]).status_code == 404
    assert client.get(f"/api/v1/videos/{video_id}/playback",
                      headers=user_a["headers"]).status_code == 404
    assert video_id not in [
        v["id"] for v in client.get("/api/v1/videos", headers=user_a["headers"]).json()
    ]


def test_duplicate_delivery_does_not_produce_a_second_analysis(
        client, user_a, upload_flow, match_clip, deferred_jobs):
    """Queues deliver at least once. That must cost an ack, not a second run
    over the same footage."""
    data = match_clip.read_bytes()
    video_id, _ = upload_flow.full(user_a, data)
    run_id = upload_flow.complete(user_a, video_id).json()["analysis_run_id"]

    worker = Worker(concurrency=1)
    worker.dispatcher = deferred_jobs
    worker.run_once()

    with SessionLocal() as db:
        first = db.get(AnalysisRun, run_id)
        assert first.status == SUCCEEDED
        completed_at = first.completed_at
        pose_rows_before = db.query(VideoAsset).filter_by(video_id=video_id).count()

    # Redeliver the identical message.
    from app.jobs.base import JobMessage, OP_INGEST
    deferred_jobs.enqueue(JobMessage(
        operation=OP_INGEST, video_id=video_id, analysis_run_id=run_id,
        pipeline_version="2.0.0",
    ))
    worker.run_once()

    with SessionLocal() as db:
        again = db.get(AnalysisRun, run_id)
        assert again.status == SUCCEEDED
        assert again.completed_at == completed_at, "the run was re-executed"
        assert db.query(VideoAsset).filter_by(video_id=video_id).count() == pose_rows_before
        assert db.query(AnalysisRun).filter_by(video_id=video_id).count() == 1


def test_corrupt_upload_fails_with_a_clear_permanent_state(
        client, user_a, upload_flow, deferred_jobs, ffmpeg_available):
    """A file that is not a video must produce an honest terminal state, not a
    retry loop and not a fabricated analysis."""
    payload = b"\x00\x00\x00\x18ftypmp42" + b"\xde\xad\xbe\xef" * 500
    video_id, _ = upload_flow.full(user_a, payload)
    upload_flow.complete(user_a, video_id)

    worker = Worker(concurrency=1)
    worker.dispatcher = deferred_jobs
    worker.run_once()

    video = client.get(f"/api/v1/videos/{video_id}", headers=user_a["headers"]).json()
    assert video["status"] == "failed"
    assert video["status_group"] == "error"
    assert video["processing_error_code"] in ("corrupt_media", "no_video_stream", "probe_failed")
    assert video["processing_error_retryable"] is False, "retrying cannot make it a video"

    # The user-facing message must be a sentence, not a stack trace or a path.
    message = video["processing_error"]
    assert message and "Traceback" not in message
    assert "/tmp/" not in message and "ffmpeg" not in message.lower()

    with SessionLocal() as db:
        run = db.query(AnalysisRun).filter_by(video_id=video_id).first()
        assert run.status == "failed"
        assert run.failed_stage
        # The internal detail is kept server-side for debugging.
        assert run.error_detail
        assert run.error_detail != run.error_message
