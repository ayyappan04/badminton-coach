"""Pre-analysis video-quality gate (V2). Runs before the main pipeline and
produces a 0-100 quality score, per-factor sub-scores, camera-cut timestamps,
and concrete recording recommendations.

All metrics are cheap classical measurements on a sampled subset of frames:
- lighting: mean luma + histogram spread
- motion blur: variance of the Laplacian (low variance = few sharp edges = blur)
- camera shake: mean absolute difference between consecutive downsampled
  grayscale frames (high sustained diff with no cuts = handheld shake)
- camera cuts: sharp drops in histogram correlation between consecutive frames

Court visibility and player-count checks are filled in by later pipeline
stages (calibration confidence, track count) — this module reports what it
can measure before any detection runs.
"""
from typing import Dict, List

import cv2
import numpy as np

QUALITY_SAMPLE_FRAMES = 60


def assess_video_quality(path: str) -> Dict:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        return {
            "score": 0, "usable": False,
            "factors": {}, "camera_cuts": [], "recommendations": ["The video file could not be read. Try re-exporting it as MP4 (H.264)."],
        }

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    step = max(1, frame_count // QUALITY_SAMPLE_FRAMES)
    lumas: List[float] = []
    blur_scores: List[float] = []
    shake_diffs: List[float] = []
    cut_timestamps: List[float] = []
    prev_small = None
    prev_hist = None

    frame_index = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if frame_index % step == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            lumas.append(float(gray.mean()))
            blur_scores.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))

            small = cv2.resize(gray, (160, 90))
            if prev_small is not None:
                shake_diffs.append(float(np.abs(small.astype(np.int16) - prev_small.astype(np.int16)).mean()))
            prev_small = small

            hist = cv2.calcHist([gray], [0], None, [64], [0, 256])
            hist = cv2.normalize(hist, hist).flatten()
            if prev_hist is not None:
                corr = float(cv2.compareHist(prev_hist.reshape(-1, 1), hist.reshape(-1, 1), cv2.HISTCMP_CORREL))
                if corr < 0.5:  # abrupt scene change between samples
                    cut_timestamps.append(round(frame_index / fps, 2))
            prev_hist = hist
        frame_index += 1
    cap.release()

    factors: Dict[str, Dict] = {}
    recommendations: List[str] = []

    # Resolution: 720p+ full marks, floor at ~360p
    res_score = min(1.0, (height / 720.0)) if height else 0.0
    factors["resolution"] = {"score": round(res_score, 2), "detail": f"{width}x{height}"}
    if height and height < 720:
        recommendations.append("Record at 720p or higher — shuttle and racket detail is lost below that.")

    fps_score = min(1.0, fps / 60.0) if fps else 0.0
    factors["frame_rate"] = {"score": round(max(fps_score, 0.5 if fps >= 24 else fps_score), 2), "detail": f"{round(fps, 1)} fps"}
    if fps < 24:
        recommendations.append("This frame rate is too low for fast shots — smashes can cross several meters between frames.")
    elif fps < 50:
        recommendations.append("Record at 60 fps when possible for better shot-timing and shuttle analysis.")

    mean_luma = float(np.mean(lumas)) if lumas else 0.0
    lighting_score = max(0.0, min(1.0, (mean_luma - 30) / 90.0))  # ~30 = near-dark, 120+ = fine
    factors["lighting"] = {"score": round(lighting_score, 2), "detail": f"mean brightness {round(mean_luma)}"}
    if lighting_score < 0.5:
        recommendations.append("The recording is dark — more court lighting will noticeably improve tracking.")

    mean_blur = float(np.mean(blur_scores)) if blur_scores else 0.0
    blur_score = max(0.0, min(1.0, mean_blur / 150.0))  # empirical: <50 very soft, >150 sharp
    factors["sharpness"] = {"score": round(blur_score, 2), "detail": f"Laplacian variance {round(mean_blur)}"}
    if blur_score < 0.4:
        recommendations.append("Frames are soft or motion-blurred — avoid digital zoom and clean the lens.")

    mean_shake = float(np.mean(shake_diffs)) if shake_diffs else 0.0
    shake_score = max(0.0, min(1.0, 1.0 - (mean_shake - 4.0) / 16.0))  # <4 = tripod-still
    factors["stability"] = {"score": round(shake_score, 2), "detail": f"mean frame diff {round(mean_shake, 1)}"}
    if shake_score < 0.5:
        recommendations.append("The camera moves a lot — record from a stable tripod position behind the baseline.")

    factors["camera_cuts"] = {"score": 1.0 if not cut_timestamps else max(0.2, 1.0 - 0.2 * len(cut_timestamps)), "detail": f"{len(cut_timestamps)} cut(s) detected"}
    if cut_timestamps:
        recommendations.append("Scene cuts were detected — tracking resets at each cut, so continuous footage analyzes better.")

    if not recommendations:
        recommendations.append("Recording quality looks good. For even better analysis, keep the full court, net, and both baselines visible.")

    weights = {"resolution": 0.2, "frame_rate": 0.15, "lighting": 0.2, "sharpness": 0.25, "stability": 0.15, "camera_cuts": 0.05}
    score = sum(factors[k]["score"] * w for k, w in weights.items())

    return {
        "score": round(score * 100),
        "usable": score >= 0.25,
        "factors": factors,
        "camera_cuts": cut_timestamps,
        "recommendations": recommendations,
    }
