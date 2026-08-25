"""Shuttle detection — the hardest CV problem in this pipeline. The shuttle is
tiny, fast, motion-blurred, and often indistinguishable from other small
bright blobs (lines, wristbands, background clutter).

This module implements a best-effort, explicitly low-confidence motion-blob
heuristic: frame differencing + background subtraction to find small, fast,
transient blobs consistent with a shuttle, with a simple nearest-neighbor
association across frames. It is intentionally conservative (returns nothing
rather than guessing wildly) and should be treated as experimental until a
trained small-object detector (Phase 2, see docs/ROADMAP.md) replaces it.
"""
from typing import List, Optional, Tuple

import cv2
import numpy as np

from app.services.cv_pipeline.types import ShuttlePoint

MIN_BLOB_AREA_PX = 2
MAX_BLOB_AREA_PX = 220
MAX_ASSOCIATION_DIST_PX = 140  # per-frame-pair search radius; scales with resolution ideally


def detect_shuttle_track(frames_native, min_resolution: Tuple[int, int] = (640, 360)) -> List[ShuttlePoint]:
    """`frames_native` is an iterator/list of (frame_index, timestamp_s, image)."""
    # Streamed deliberately: materialising every native frame costs
    # duration x fps x width x height x 3 bytes — ~94 GB for an 8-minute 1080p
    # match, which OOM-kills the worker. Only the per-frame blob centroids are
    # retained, which are a few hundred bytes per frame.
    bg_subtractor = None
    candidates_by_frame = []

    for frame_index, timestamp_s, image in frames_native:
        if bg_subtractor is None:
            h, w = image.shape[:2]
            if w < min_resolution[0] or h < min_resolution[1]:
                return []  # too low-res for a small fast object to be resolved
            bg_subtractor = cv2.createBackgroundSubtractorMOG2(
                history=30, varThreshold=25, detectShadows=False
            )
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        fg_mask = bg_subtractor.apply(gray)
        fg_mask = cv2.morphologyEx(fg_mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        contours, _ = cv2.findContours(fg_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        blobs = []
        for c in contours:
            area = cv2.contourArea(c)
            if MIN_BLOB_AREA_PX <= area <= MAX_BLOB_AREA_PX:
                m = cv2.moments(c)
                if m["m00"] == 0:
                    continue
                cx, cy = m["m10"] / m["m00"], m["m01"] / m["m00"]
                blobs.append((cx, cy, area))
        candidates_by_frame.append((frame_index, timestamp_s, blobs))

    if not candidates_by_frame:
        return []

    # Greedy nearest-neighbor association across consecutive frames to build a
    # single continuous track — real shuttle tracking would use multiple
    # hypothesis tracking; this is a deliberately simple MVP approximation.
    points: List[ShuttlePoint] = []
    prev_point: Optional[Tuple[float, float]] = None

    for frame_index, timestamp_s, blobs in candidates_by_frame:
        if not blobs:
            continue
        if prev_point is None:
            # pick the smallest plausible blob as a starting guess (favors shuttle over larger clutter)
            cx, cy, area = min(blobs, key=lambda b: b[2])
        else:
            px, py = prev_point
            cx, cy, area = min(blobs, key=lambda b: (b[0] - px) ** 2 + (b[1] - py) ** 2)
            dist = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
            if dist > MAX_ASSOCIATION_DIST_PX:
                continue  # discontinuity too large to trust as the same object

        confidence = 0.25 if prev_point is None else max(0.1, 0.4 - (area / MAX_BLOB_AREA_PX) * 0.15)
        points.append(ShuttlePoint(frame_index=frame_index, timestamp_s=timestamp_s, x_px=cx, y_px=cy, confidence=confidence))
        prev_point = (cx, cy)

    return refine_track(points)


def refine_track(points: List[ShuttlePoint]) -> List[ShuttlePoint]:
    """Phase-3 trajectory refinement: velocity-outlier rejection + a light
    positional median filter, applied per continuous segment (segments split
    at frame gaps). Points that survive inside long, consistent segments get a
    modest confidence boost — still capped well below trained-detector levels,
    because a consistent wrong track is still wrong."""
    if len(points) < 5:
        return points

    # split into segments at frame gaps
    segments: List[List[ShuttlePoint]] = [[points[0]]]
    for prev, cur in zip(points, points[1:]):
        if cur.frame_index - prev.frame_index > 6:
            segments.append([cur])
        else:
            segments[-1].append(cur)

    refined: List[ShuttlePoint] = []
    for seg in segments:
        if len(seg) < 3:
            refined.extend(seg)
            continue

        # reject velocity outliers: a point whose step distance is far beyond
        # the segment's median step is clutter grabbed by the greedy matcher
        steps = [
            ((b.x_px - a.x_px) ** 2 + (b.y_px - a.y_px) ** 2) ** 0.5
            for a, b in zip(seg, seg[1:])
        ]
        sorted_steps = sorted(steps)
        median_step = sorted_steps[len(sorted_steps) // 2]
        keep = [seg[0]]
        for i in range(1, len(seg)):
            step = steps[i - 1]
            if median_step > 0 and step > median_step * 4 and step > 40:
                continue
            keep.append(seg[i])
        if len(keep) < 3:
            refined.extend(keep)
            continue

        # 3-point positional median filter to damp blob-centroid jitter
        seg_conf_boost = min(0.15, 0.02 * len(keep))  # longer consistent segment -> slightly more trust
        for i, p in enumerate(keep):
            window = keep[max(0, i - 1):i + 2]
            xs = sorted(w.x_px for w in window)
            ys = sorted(w.y_px for w in window)
            refined.append(ShuttlePoint(
                frame_index=p.frame_index, timestamp_s=p.timestamp_s,
                x_px=xs[len(xs) // 2], y_px=ys[len(ys) // 2],
                confidence=round(min(0.5, p.confidence + seg_conf_boost), 2),
            ))

    return refined


def estimate_speed_mps(points: List[ShuttlePoint], px_per_meter: Optional[float]) -> List[float]:
    """Optional helper: rough speed estimate between consecutive shuttle points,
    given an approximate pixels-per-meter scale from calibration. Highly
    approximate — real speed depends on depth/perspective the single camera
    can't resolve precisely."""
    if not px_per_meter or px_per_meter <= 0:
        return []
    speeds = []
    for a, b in zip(points, points[1:]):
        dt = b.timestamp_s - a.timestamp_s
        if dt <= 0:
            continue
        dist_px = ((b.x_px - a.x_px) ** 2 + (b.y_px - a.y_px) ** 2) ** 0.5
        speeds.append((dist_px / px_per_meter) / dt)
    return speeds
