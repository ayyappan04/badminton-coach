"""Durable persistence of the full structured PipelineResult.

The MVP kept this object in a module-level dict. The docstring on
`analysis_service` was honest about the consequence: after a restart the
richer structures were gone, so `finalize_after_identity` silently produced a
thinner analysis than the same video would have produced a minute earlier. On
a container platform, where restarts are routine and the process that finishes
a job is often not the one that started it, that is not a caching detail — it
is nondeterministic output.

The result is written to object storage as gzipped JSON instead of into
Postgres. It is a few tens of megabytes of per-frame arrays with no query
pattern beyond "give me all of it": exactly the shape the brief's data-capture
rules say belongs in a bucket, not in a row.
"""
from __future__ import annotations

import gzip
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from app.core import config
from app.core.observability import log
from app.services.cv_pipeline.types import (
    CalibrationResult, DetectionBox, PipelineResult, PoseSample, RallySegment,
    ShotEvent, ShuttlePoint, Track, VideoMeta,
)
from app.storage import get_storage
from app.storage.paths import artifact_key

logger = logging.getLogger("app.artifacts")

ARTIFACT_NAME = "pipeline_result.json.gz"
ARTIFACT_SCHEMA = 1


def to_dict(result: PipelineResult) -> Dict[str, Any]:
    cal = result.calibration
    return {
        "schema": ARTIFACT_SCHEMA,
        "meta": {
            "fps": result.meta.fps, "frame_count": result.meta.frame_count,
            "width": result.meta.width, "height": result.meta.height,
            "duration_s": result.meta.duration_s,
        },
        "calibration": {
            "method": cal.method, "court_corners_px": cal.court_corners_px,
            "homography": cal.homography.tolist() if cal.homography is not None else None,
            "confidence": cal.confidence, "notes": cal.notes,
            "limitations": list(cal.limitations or []),
        },
        "tracks": [
            {"track_id": t.track_id, "role": t.role,
             "boxes": [[b.frame_index, b.x, b.y, b.w, b.h, b.confidence] for b in t.boxes]}
            for t in result.tracks
        ],
        # Positional rows rather than repeated keys: on a 40-minute match this
        # is the difference between a ~200 MB artifact and a ~40 MB one.
        "poses": [
            [p.track_id, p.frame_index, p.timestamp_s, p.confidence, p.landmarks]
            for p in result.poses
        ],
        "shuttle_points": [
            [s.frame_index, s.timestamp_s, s.x_px, s.y_px, s.confidence]
            for s in result.shuttle_points
        ],
        "rallies": [
            [r.rally_index, r.start_frame, r.end_frame, r.start_timestamp_s,
             r.end_timestamp_s, r.confidence]
            for r in result.rallies
        ],
        "shots": [
            [s.track_id, s.rally_index, s.frame_index, s.timestamp_s, s.shot_type,
             s.side, s.contact_height, s.intent, s.outcome, s.confidence]
            for s in result.shots
        ],
        "biomechanics": result.biomechanics,
        "tactics": result.tactics,
        "limitations": list(result.limitations or []),
        "quality": result.quality,
        "phases_by_rally": {str(k): v for k, v in (result.phases_by_rally or {}).items()},
    }


def from_dict(data: Dict[str, Any]) -> PipelineResult:
    meta = data.get("meta") or {}
    cal = data.get("calibration") or {}
    homography = cal.get("homography")

    return PipelineResult(
        meta=VideoMeta(
            fps=meta.get("fps", 0.0), frame_count=meta.get("frame_count", 0),
            width=meta.get("width", 0), height=meta.get("height", 0),
            duration_s=meta.get("duration_s", 0.0),
        ),
        calibration=CalibrationResult(
            method=cal.get("method", "unknown"),
            court_corners_px=cal.get("court_corners_px") or [],
            homography=np.array(homography) if homography else None,
            confidence=cal.get("confidence", 0.0), notes=cal.get("notes", ""),
            limitations=cal.get("limitations") or [],
        ),
        tracks=[
            Track(track_id=t["track_id"], role=t.get("role", "unassigned"),
                  boxes=[DetectionBox(frame_index=b[0], x=b[1], y=b[2], w=b[3], h=b[4],
                                      confidence=b[5]) for b in t.get("boxes", [])])
            for t in data.get("tracks", [])
        ],
        poses=[
            PoseSample(track_id=p[0], frame_index=p[1], timestamp_s=p[2],
                       confidence=p[3], landmarks=p[4])
            for p in data.get("poses", [])
        ],
        shuttle_points=[
            ShuttlePoint(frame_index=s[0], timestamp_s=s[1], x_px=s[2], y_px=s[3],
                         confidence=s[4])
            for s in data.get("shuttle_points", [])
        ],
        rallies=[
            RallySegment(rally_index=r[0], start_frame=r[1], end_frame=r[2],
                         start_timestamp_s=r[3], end_timestamp_s=r[4], confidence=r[5])
            for r in data.get("rallies", [])
        ],
        shots=[
            ShotEvent(track_id=s[0], rally_index=s[1], frame_index=s[2], timestamp_s=s[3],
                      shot_type=s[4], side=s[5], contact_height=s[6], intent=s[7],
                      outcome=s[8], confidence=s[9])
            for s in data.get("shots", [])
        ],
        biomechanics=data.get("biomechanics") or {},
        tactics=data.get("tactics") or {},
        limitations=data.get("limitations") or [],
        quality=data.get("quality"),
        phases_by_rally={int(k): v for k, v in (data.get("phases_by_rally") or {}).items()},
    )


def write_local(result: PipelineResult, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(dest, "wt", encoding="utf-8", compresslevel=6) as fh:
        json.dump(to_dict(result), fh, separators=(",", ":"), default=float)
    return dest


def read_local(path: Path) -> PipelineResult:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return from_dict(json.load(fh))


def key_for(user_id: str, video_id: str, pipeline_version: str) -> str:
    return artifact_key(user_id, video_id, pipeline_version, ARTIFACT_NAME)


def publish(result: PipelineResult, *, user_id: str, video_id: str,
            pipeline_version: str, workdir: Path) -> tuple[str, str, int]:
    """Write and upload. Returns (bucket, key, size_bytes)."""
    local = write_local(result, workdir / ARTIFACT_NAME)
    key = key_for(user_id, video_id, pipeline_version)
    get_storage().upload_file(config.BUCKET_DERIVED, key, local, "application/gzip")
    size = local.stat().st_size
    log(logger, logging.INFO, "pipeline artifact published", key=key, size_bytes=size)
    return config.BUCKET_DERIVED, key, size


def fetch(*, user_id: str, video_id: str, pipeline_version: str,
          workdir: Optional[Path] = None) -> Optional[PipelineResult]:
    """Rehydrate a PipelineResult. Returns None when no artifact exists —
    callers must still degrade gracefully for videos analyzed before this
    existed."""
    import tempfile
    key = key_for(user_id, video_id, pipeline_version)
    target_dir = workdir or Path(tempfile.mkdtemp(prefix="ss-artifact-"))
    local = target_dir / ARTIFACT_NAME
    try:
        get_storage().download_to(config.BUCKET_DERIVED, key, local)
        return read_local(local)
    except Exception as exc:  # noqa: BLE001 — a missing artifact is expected, not exceptional
        log(logger, logging.INFO, "pipeline artifact unavailable", key=key, reason=str(exc)[:200])
        return None
    finally:
        if workdir is None:
            import shutil
            shutil.rmtree(target_dir, ignore_errors=True)
