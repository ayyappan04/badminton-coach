"""Classical court-line detection via color thresholding + Hough line transform.

Badminton court lines are a solid, high-contrast color (usually white or
yellow) against the court surface. We threshold for bright, low-saturation
pixels, run a probabilistic Hough transform on the resulting mask, and use the
extreme detected line positions to estimate the outer court boundary. This is
a best-effort classical approach — it degrades on cluttered backgrounds,
partial court visibility, or unusual lighting, so a low-confidence result
should always fall back to user-assisted 4-point calibration in the product
flow (see docs/CV_PIPELINE.md).
"""
from typing import List, Optional

import cv2
import numpy as np

from app.services.cv_pipeline.types import Frame, CalibrationResult
from app.services.cv_pipeline import court_geometry as geo

MIN_CONFIDENCE_FOR_AUTO = 0.35


def _line_mask(image: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    # bright, low-saturation pixels: candidate court-line paint (white or yellow lines)
    lower = np.array([0, 0, 170])
    upper = np.array([180, 90, 255])
    mask = cv2.inRange(hsv, lower, upper)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    return mask


def detect_court(frames: List[Frame]) -> CalibrationResult:
    if not frames:
        return CalibrationResult(
            method="fallback_full_frame", court_corners_px=[], homography=None,
            confidence=0.0, notes="No frames available for calibration.",
            limitations=["no_frames"],
        )

    h, w = frames[0].image.shape[:2]

    # Aggregate the line mask across a handful of frames to reduce noise from
    # players/shuttle briefly occluding lines in any single frame.
    sample = frames[:: max(1, len(frames) // 15)][:15]
    agg = np.zeros((h, w), dtype=np.uint32)
    for f in sample:
        agg += (_line_mask(f.image) > 0).astype(np.uint32)
    mask = (agg >= max(1, len(sample) // 3)).astype(np.uint8) * 255

    edges = cv2.Canny(mask, 50, 150)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=60, minLineLength=int(min(w, h) * 0.15), maxLineGap=20)

    if lines is None or len(lines) < 4:
        return _fallback(w, h, notes="Too few line segments detected; camera angle, lighting, or occlusion likely prevented reliable court-line detection.")

    segments = np.asarray(lines).reshape(-1, 4).astype(float)

    # V2: split segments into near-horizontal and near-vertical families by
    # angle, then intersect the extreme lines of each family. Unlike the V1
    # axis-aligned bounding box, this yields a perspective-aware quadrilateral
    # (baselines converge toward the far court in typical baseline footage).
    horizontal, vertical = [], []
    for x1, y1, x2, y2 in segments:
        angle = abs(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        if angle > 90:
            angle = 180 - angle
        if angle < 35:
            horizontal.append((x1, y1, x2, y2))
        elif angle > 55:
            vertical.append((x1, y1, x2, y2))

    quad = _quad_from_families(horizontal, vertical)

    if quad is not None:
        corners_px = quad
        method = "auto_hough_quad"
        family_support = min(1.0, (len(horizontal) + len(vertical)) / 30.0)
    else:
        # fall back to the V1 axis-aligned extent when families are too sparse
        xs = segments[:, [0, 2]].flatten()
        ys = segments[:, [1, 3]].flatten()
        corners_px = [
            [float(xs.min()), float(ys.min())],
            [float(xs.max()), float(ys.min())],
            [float(xs.max()), float(ys.max())],
            [float(xs.min()), float(ys.max())],
        ]
        method = "auto_hough"
        family_support = min(1.0, len(segments) / 40.0) * 0.7

    coverage = _quad_area(corners_px) / (w * h)
    confidence = float(max(0.0, min(0.9, 0.45 * min(coverage * 1.6, 1.0) + 0.55 * family_support)))

    limitations = []
    if confidence < MIN_CONFIDENCE_FOR_AUTO:
        limitations.append("low_confidence_auto_detection")
    if coverage < 0.3:
        limitations.append("court_partially_visible")

    return CalibrationResult(
        method=method,
        court_corners_px=corners_px,
        homography=_solve_homography(corners_px),
        confidence=confidence,
        notes="Estimated from detected court-line segments; treat as approximate." if confidence < 0.7 else "Estimated from detected court-line segments.",
        limitations=limitations,
    )


def _quad_from_families(horizontal, vertical):
    """Intersect the topmost/bottommost horizontal lines with the leftmost/
    rightmost vertical lines. Returns [TL, TR, BR, BL] or None if either
    family lacks two sufficiently separated lines."""
    if len(horizontal) < 2 or len(vertical) < 2:
        return None

    top = min(horizontal, key=lambda s: (s[1] + s[3]) / 2)
    bottom = max(horizontal, key=lambda s: (s[1] + s[3]) / 2)
    left = min(vertical, key=lambda s: (s[0] + s[2]) / 2)
    right = max(vertical, key=lambda s: (s[0] + s[2]) / 2)

    if abs((top[1] + top[3]) / 2 - (bottom[1] + bottom[3]) / 2) < 20:
        return None
    if abs((left[0] + left[2]) / 2 - (right[0] + right[2]) / 2) < 20:
        return None

    tl = _intersect(top, left)
    tr = _intersect(top, right)
    br = _intersect(bottom, right)
    bl = _intersect(bottom, left)
    if any(p is None for p in (tl, tr, br, bl)):
        return None
    quad = [list(tl), list(tr), list(br), list(bl)]
    if _quad_area(quad) <= 0 or not _is_convex(quad):
        return None
    return quad


def _intersect(seg_a, seg_b):
    x1, y1, x2, y2 = seg_a
    x3, y3, x4, y4 = seg_b
    denom = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(denom) < 1e-9:
        return None
    px = ((x1 * y2 - y1 * x2) * (x3 - x4) - (x1 - x2) * (x3 * y4 - y3 * x4)) / denom
    py = ((x1 * y2 - y1 * x2) * (y3 - y4) - (y1 - y2) * (x3 * y4 - y3 * x4)) / denom
    return (float(px), float(py))


def _quad_area(quad) -> float:
    area = 0.0
    for i in range(4):
        x1, y1 = quad[i]
        x2, y2 = quad[(i + 1) % 4]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2


def _is_convex(quad) -> bool:
    signs = []
    for i in range(4):
        ox, oy = quad[i]
        ax, ay = quad[(i + 1) % 4]
        bx, by = quad[(i + 2) % 4]
        cross = (ax - ox) * (by - ay) - (ay - oy) * (bx - ax)
        signs.append(cross > 0)
    return all(signs) or not any(signs)


def _fallback(w: int, h: int, notes: str) -> CalibrationResult:
    margin_x, margin_y = w * 0.05, h * 0.05
    corners_px = [
        [margin_x, margin_y],
        [w - margin_x, margin_y],
        [w - margin_x, h - margin_y],
        [margin_x, h - margin_y],
    ]
    return CalibrationResult(
        method="fallback_full_frame",
        court_corners_px=corners_px,
        homography=_solve_homography(corners_px),
        confidence=0.15,
        notes=notes + " Falling back to an approximate full-frame boundary; user-assisted calibration is strongly recommended.",
        limitations=["auto_detection_failed", "needs_user_calibration"],
    )


def solve_homography_from_corners(corners_px: List[List[float]]) -> Optional[np.ndarray]:
    return _solve_homography(corners_px)


def _solve_homography(corners_px: List[List[float]]) -> Optional[np.ndarray]:
    if len(corners_px) != 4:
        return None
    src = np.array(corners_px, dtype=np.float32)
    dst = np.array(geo.DOUBLES_COURT_CORNERS, dtype=np.float32)
    homography, _ = cv2.findHomography(src, dst)
    return homography


def pixel_to_court(homography: np.ndarray, x_px: float, y_px: float):
    pt = np.array([[[x_px, y_px]]], dtype=np.float32)
    out = cv2.perspectiveTransform(pt, homography)
    return float(out[0][0][0]), float(out[0][0][1])
