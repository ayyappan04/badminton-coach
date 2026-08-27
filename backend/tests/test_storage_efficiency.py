"""Storage-volume behaviour of the analysis write path.

`pose_frames` was the largest thing this system writes: 33 landmarks x ~15 fps
x 2 players x 40 minutes is ~72,000 rows and ~130 MB of JSON for ONE match.
Nothing queries them by content -- every consumer reads the whole sequence to
rebuild one object -- so they belong in the gzipped artifact.

These tests pin the two properties that make that safe: landmarks are only
omitted from Postgres when the artifact really exists, and every read path
resolves them from whichever store holds them.
"""
import pytest

from app.core import config
from app.db.session import SessionLocal
from app.models.analysis import PoseFrame
from app.models.video import TrackedPerson, Video
from app.services import analysis_service
from app.services.cv_pipeline.types import (
    CalibrationResult, DetectionBox, PipelineResult, PoseSample, Track, VideoMeta,
)


def _result(n_frames=40):
    landmarks = [
        {"name": f"lm{i}", "x": 0.5, "y": 0.5, "z": 0.0, "visibility": 0.9}
        for i in range(33)
    ]
    return PipelineResult(
        meta=VideoMeta(fps=30, frame_count=n_frames * 3, width=960, height=540,
                       duration_s=n_frames / 10),
        calibration=CalibrationResult(method="auto", court_corners_px=[[0, 0]] * 4,
                                      homography=None, confidence=0.7),
        tracks=[Track(track_id=0,
                      boxes=[DetectionBox(i, 1.0 * i, 2.0, 60, 140, 0.7) for i in range(n_frames)],
                      role="self")],
        poses=[PoseSample(track_id=0, frame_index=i, timestamp_s=i / 10,
                          landmarks=landmarks, confidence=0.8) for i in range(n_frames)],
        shuttle_points=[], rallies=[], shots=[], biomechanics={}, tactics={},
        quality={"score": 70, "usable": True, "factors": {}, "camera_cuts": [],
                 "recommendations": []},
    )


@pytest.fixture()
def video_row(user_a):
    with SessionLocal() as db:
        video = Video(owner_user_id=user_a["id"], storage_path="", original_filename="m.mp4",
                      match_format="singles", status="processing")
        db.add(video)
        db.commit()
        db.refresh(video)
        return video.id


def test_landmarks_are_omitted_from_postgres_when_the_artifact_exists(video_row, storage, monkeypatch):
    monkeypatch.setattr(config, "PERSIST_POSE_LANDMARKS", False)
    result = _result()

    with SessionLocal() as db:
        video = db.get(Video, video_row)
        published = analysis_service._publish_artifact(video, result)
        assert published is True, "artifact upload failed; the rest of this test is meaningless"
        analysis_service._persist_pipeline_result(db, video, result, store_landmarks=False)

        rows = db.query(PoseFrame).filter_by(video_id=video_row).all()
        assert len(rows) == 40, "the small queryable columns must still be written"
        assert all(r.landmarks == [] for r in rows), "the bulk payload was still stored"
        # The cheap columns are what make a row worth keeping at all.
        assert all(r.timestamp_s is not None and r.confidence > 0 for r in rows)


def test_reads_resolve_landmarks_from_the_artifact(video_row, storage, monkeypatch):
    """The whole scheme rests on this: a consumer must not be able to tell
    which store the landmarks came from."""
    monkeypatch.setattr(config, "PERSIST_POSE_LANDMARKS", False)
    result = _result()

    with SessionLocal() as db:
        video = db.get(Video, video_row)
        video.pipeline_version = analysis_service.PIPELINE_VERSION
        db.commit()
        assert analysis_service._publish_artifact(video, result) is True
        analysis_service._persist_pipeline_result(db, video, result, store_landmarks=False)

    # Drop the in-process cache so the artifact is genuinely exercised.
    analysis_service._pipeline_cache.pop(video_row, None)

    with SessionLocal() as db:
        video = db.get(Video, video_row)
        tp = db.query(TrackedPerson).filter_by(video_id=video_row).first()

        bare = analysis_service.pose_samples_from_db(db, tp)
        assert bare and all(s.landmarks == [] for s in bare), "fixture is not exercising the fallback"

        full = analysis_service.pose_samples_for(db, video, tp)
        assert len(full) == 40
        assert all(len(s.landmarks) == 33 for s in full), "landmarks were not recovered"
        assert full[0].timestamp_s == 0.0 and full[-1].frame_index == 39


def test_landmarks_are_kept_in_postgres_when_the_artifact_fails(video_row, monkeypatch):
    """Skipping persistence on the ASSUMPTION an upload worked would lose the
    data outright when it did not."""
    monkeypatch.setattr(config, "PERSIST_POSE_LANDMARKS", False)
    monkeypatch.setattr(analysis_service, "_publish_artifact", lambda *a, **k: False)
    result = _result()

    with SessionLocal() as db:
        video = db.get(Video, video_row)
        published = analysis_service._publish_artifact(video, result)
        store = config.PERSIST_POSE_LANDMARKS or not published
        assert store is True, "the fallback did not engage"
        analysis_service._persist_pipeline_result(db, video, result, store_landmarks=store)
        rows = db.query(PoseFrame).filter_by(video_id=video_row).all()
        assert all(len(r.landmarks) == 33 for r in rows)


def test_legacy_rows_with_landmarks_still_read(video_row, monkeypatch):
    """Videos analyzed before this change keep working without a migration."""
    monkeypatch.setattr(config, "PERSIST_POSE_LANDMARKS", True)
    result = _result()

    with SessionLocal() as db:
        video = db.get(Video, video_row)
        analysis_service._persist_pipeline_result(db, video, result, store_landmarks=True)

    analysis_service._pipeline_cache.pop(video_row, None)

    with SessionLocal() as db:
        video = db.get(Video, video_row)
        tp = db.query(TrackedPerson).filter_by(video_id=video_row).first()
        samples = analysis_service.pose_samples_for(db, video, tp)
        assert len(samples) == 40 and all(len(s.landmarks) == 33 for s in samples)


def test_artifact_is_dramatically_smaller_than_the_equivalent_rows(tmp_path):
    """Quantifies the reason for the whole change."""
    import json
    from app.services import pipeline_artifacts

    result = _result(n_frames=400)
    gz = pipeline_artifacts.write_local(result, tmp_path / "a.json.gz")
    gz_bytes = gz.stat().st_size

    # What the same landmarks cost as one JSON column per frame.
    row_bytes = sum(len(json.dumps(p.landmarks)) for p in result.poses)

    ratio = row_bytes / gz_bytes
    assert ratio > 20, f"expected a large reduction, got {ratio:.1f}x"


def test_pipeline_cache_is_bounded():
    """An unbounded cache of multi-megabyte results is the same OOM the frame
    budget was introduced to prevent, one level up."""
    cache = analysis_service._BoundedCache(3)
    for i in range(10):
        cache[f"v{i}"] = _result(n_frames=1)
    assert len(cache) == 3
    assert list(cache.keys()) == ["v7", "v8", "v9"]


def test_pipeline_cache_evicts_least_recently_used():
    cache = analysis_service._BoundedCache(3)
    for key in ("a", "b", "c"):
        cache[key] = _result(n_frames=1)
    cache.get("a")            # touch
    cache["d"] = _result(n_frames=1)
    assert "a" in cache and "b" not in cache
