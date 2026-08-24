"""Run every generated badminton scenario through the REAL CV pipeline and
print a measured results matrix.

Usage:
    python -m tests.run_video_matrix            # from backend/, venv active

Everything printed is measured at runtime — no expected values are assumed.
"""
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/bc-matrix.db")
os.environ.setdefault("JWT_SECRET", "matrix-run-only")
os.environ.setdefault("STORAGE_DIR", "/tmp/bc-matrix-storage")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.video_scenarios import build_all  # noqa: E402
from app.services.cv_pipeline.pipeline import run_pipeline, PIPELINE_VERSION  # noqa: E402


def main():
    out_dir = Path("/tmp/bc-scenarios")
    scenarios = build_all(out_dir)
    print(f"pipeline version: {PIPELINE_VERSION}\n")

    rows = []
    for name, info in scenarios.items():
        path = info["path"]
        started = time.time()
        error = None
        try:
            result = run_pipeline(str(path))
        except Exception as exc:  # noqa: BLE001 - we want to record, not crash
            result, error = None, f"{type(exc).__name__}: {exc}"
        elapsed = time.time() - started

        if result is None:
            rows.append({
                "scenario": name, "error": error, "elapsed_s": round(elapsed, 1),
            })
            continue

        rows.append({
            "scenario": name,
            "description": info["description"],
            "size_mb": round(path.stat().st_size / 1e6, 2),
            "resolution": f"{result.meta.width}x{result.meta.height}",
            "fps": round(result.meta.fps, 1),
            "duration_s": round(result.meta.duration_s, 1),
            "quality_score": result.quality["score"] if result.quality else None,
            "usable": result.quality["usable"] if result.quality else None,
            "camera_cuts": len(result.quality["camera_cuts"]) if result.quality else None,
            "court_method": result.calibration.method,
            "court_conf": round(result.calibration.confidence, 2),
            "tracks": len(result.tracks),
            "poses": len(result.poses),
            "shuttle_pts": len(result.shuttle_points),
            "rallies": len(result.rallies),
            "shots": len(result.shots),
            "limitations": result.limitations,
            "recommendations": (result.quality or {}).get("recommendations", [])[:2],
            "elapsed_s": round(elapsed, 1),
            "realtime_ratio": round(elapsed / max(result.meta.duration_s, 0.1), 1),
        })
        print(f"  {name:18} q={rows[-1]['quality_score']:>3}  court={rows[-1]['court_conf']:.2f}  "
              f"tracks={rows[-1]['tracks']}  rallies={rows[-1]['rallies']}  "
              f"shots={rows[-1]['shots']}  {rows[-1]['elapsed_s']}s "
              f"({rows[-1]['realtime_ratio']}x realtime)")

    dest = Path(__file__).resolve().parent.parent.parent / "docs" / "evidence" / "video-matrix.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(rows, indent=2))
    print(f"\nwrote {dest}")
    return rows


if __name__ == "__main__":
    main()
