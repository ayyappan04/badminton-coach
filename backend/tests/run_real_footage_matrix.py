"""Run REAL badminton footage through the CV pipeline and score the stages
that synthetic clips cannot exercise: pose estimation, player tracking, and
shot recognition.

Footage sourcing
----------------
Clips come from Wikimedia Commons under CC0 / public-domain / CC BY / CC BY-SA
licences, which explicitly permit download and reuse with attribution. They are
NOT committed to the repository — `fetch_real_footage.py` downloads them on
demand, and `docs/evidence/real-footage-attribution.md` records the licence and
author for each one.

Broadcast footage from BWF or other rights-holders is deliberately NOT used:
downloading it would breach the platform terms and the licence. See
`docs/BWF_MANUAL_TEST_PROTOCOL.md` for the observational protocol that covers
that footage lawfully instead.

Usage:
    python -m tests.fetch_real_footage        # download (polite, cached)
    python -m tests.run_real_footage_matrix   # analyse
"""
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/bc-real-matrix.db")
os.environ.setdefault("JWT_SECRET", "real-matrix-run-only")
os.environ.setdefault("STORAGE_DIR", "/tmp/bc-real-matrix-storage")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.cv_pipeline.pipeline import run_pipeline, PIPELINE_VERSION  # noqa: E402
from tests.footage_manifest import FOOTAGE, FOOTAGE_DIR  # noqa: E402


def summarise(result, elapsed: float) -> dict:
    """Derive the per-stage quality signals we care about."""
    tracks = result.tracks
    poses = result.poses

    # Pose coverage: what share of tracked person-frames produced landmarks.
    person_frames = sum(len(t.boxes) for t in tracks)
    pose_coverage = (len(poses) / person_frames) if person_frames else 0.0
    mean_pose_conf = (sum(p.confidence for p in poses) / len(poses)) if poses else 0.0

    # Track fragmentation: more tracks than players present means identity
    # breaks. Persistence = mean track length relative to the longest track.
    lengths = sorted((len(t.boxes) for t in tracks), reverse=True)
    longest = lengths[0] if lengths else 0
    persistence = (sum(lengths[:4]) / (4 * longest)) if longest else 0.0

    shots_by_type = {}
    for s in result.shots:
        shots_by_type[s.shot_type] = shots_by_type.get(s.shot_type, 0) + 1

    return {
        "resolution": f"{result.meta.width}x{result.meta.height}",
        "fps": round(result.meta.fps, 1),
        "duration_s": round(result.meta.duration_s, 1),
        "quality_score": (result.quality or {}).get("score"),
        "court_method": result.calibration.method,
        "court_conf": round(result.calibration.confidence, 2),
        "tracks": len(tracks),
        "person_frames": person_frames,
        "poses": len(poses),
        "pose_coverage_pct": round(pose_coverage * 100, 1),
        "mean_pose_confidence": round(mean_pose_conf, 2),
        "track_persistence": round(persistence, 2),
        "shuttle_points": len(result.shuttle_points),
        "rallies": len(result.rallies),
        "shots": len(result.shots),
        "shots_by_type": shots_by_type,
        "limitations": result.limitations,
        "elapsed_s": round(elapsed, 1),
        "realtime_ratio": round(elapsed / max(result.meta.duration_s, 0.1), 2),
    }


def main():
    rows = []
    print(f"pipeline {PIPELINE_VERSION} — REAL footage\n")
    for entry in FOOTAGE:
        path = FOOTAGE_DIR / entry["file"]
        if not path.exists():
            print(f"  {entry['key']:20} SKIPPED (not downloaded)")
            continue
        started = time.time()
        try:
            result = run_pipeline(str(path))
            row = {"key": entry["key"], "scenario": entry["scenario"],
                   "licence": entry["licence"], **summarise(result, time.time() - started)}
        except Exception as exc:  # noqa: BLE001 — record, don't crash the matrix
            row = {"key": entry["key"], "scenario": entry["scenario"],
                   "error": f"{type(exc).__name__}: {exc}",
                   "elapsed_s": round(time.time() - started, 1)}
        rows.append(row)
        if "error" in row:
            print(f"  {row['key']:20} ERROR {row['error'][:60]}")
        else:
            print(f"  {row['key']:20} {row['resolution']:>10} q={row['quality_score']:>3} "
                  f"court={row['court_conf']:.2f} tracks={row['tracks']:>2} "
                  f"pose={row['pose_coverage_pct']:>5.1f}% shots={row['shots']:>3} "
                  f"rallies={row['rallies']:>2} {row['realtime_ratio']}x RT")

    dest = Path(__file__).resolve().parent.parent.parent / "docs" / "evidence" / "real-footage-matrix.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(rows, indent=2))
    print(f"\nwrote {dest}")
    return rows


if __name__ == "__main__":
    main()
