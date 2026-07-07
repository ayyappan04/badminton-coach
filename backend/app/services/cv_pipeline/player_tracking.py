"""Player detection & multi-object tracking using OpenCV's built-in HOG person
detector plus a simple IOU-based greedy tracker.

This is intentionally the least accurate stage in the MVP pipeline — it is the
first candidate for replacement with a modern detector (YOLOv8/RT-DETR) and a
proper tracker (ByteTrack/DeepSORT) once the product needs robust doubles
tracking through frequent occlusion (see docs/ROADMAP.md, Phase 2). It is
still real, working detection — not a stub — and is adequate for MVP-level
singles positioning/movement insights.
"""
from typing import List, Dict

import cv2
import numpy as np

from app.services.cv_pipeline.types import Frame, DetectionBox, Track

_hog = cv2.HOGDescriptor()
_hog.setSVMDetector(cv2.HOGDescriptor_getDefaultPeopleDetector())


def detect_people(image: np.ndarray) -> List[DetectionBox]:
    # HOG works on ~1x scale reasonably; downscale very large frames for speed.
    h, w = image.shape[:2]
    scale = 1.0
    if max(h, w) > 960:
        scale = 960 / max(h, w)
        image = cv2.resize(image, (int(w * scale), int(h * scale)))

    boxes, weights = _hog.detectMultiScale(image, winStride=(8, 8), padding=(8, 8), scale=1.05)
    detections = []
    for (x, y, bw, bh), weight in zip(boxes, weights):
        conf = float(1 / (1 + np.exp(-weight)))  # squashes HOG SVM score to (0,1)
        detections.append(DetectionBox(
            frame_index=-1,  # filled in by caller
            x=x / scale, y=y / scale, w=bw / scale, h=bh / scale,
            confidence=conf,
        ))
    return detections


def _iou(a: DetectionBox, b: DetectionBox) -> float:
    ax2, ay2 = a.x + a.w, a.y + a.h
    bx2, by2 = b.x + b.w, b.y + b.h
    inter_x1, inter_y1 = max(a.x, b.x), max(a.y, b.y)
    inter_x2, inter_y2 = min(ax2, bx2), min(ay2, by2)
    inter_w, inter_h = max(0.0, inter_x2 - inter_x1), max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h
    union_area = a.w * a.h + b.w * b.h - inter_area
    return inter_area / union_area if union_area > 0 else 0.0


def _predicted_center(track: Track):
    """Constant-velocity prediction of the track's next center from its last
    two observations — used to bridge short occlusion gaps (V2)."""
    if len(track.boxes) < 2:
        b = track.boxes[-1]
        return b.x + b.w / 2, b.y + b.h / 2
    a, b = track.boxes[-2], track.boxes[-1]
    frames_apart = max(1, b.frame_index - a.frame_index)
    vx = (b.x - a.x) / frames_apart
    vy = (b.y - a.y) / frames_apart
    return b.x + b.w / 2 + vx, b.y + b.h / 2 + vy


def track_players(
    frames: List[Frame],
    max_missed_frames: int = 8,
    iou_threshold: float = 0.25,
    camera_cut_timestamps: List[float] = None,
    fps_sampled: float = 10.0,
) -> List[Track]:
    cut_frames = set()
    for ts in camera_cut_timestamps or []:
        cut_frames.add(round(ts * fps_sampled))

    active: Dict[int, Track] = {}
    finished: List[Track] = []
    last_seen: Dict[int, int] = {}
    next_id = 0

    for frame in frames:
        # Camera cut: identities cannot survive a scene change — hard reset
        # rather than letting the IOU matcher glue unrelated people together.
        if frame.index in cut_frames:
            finished.extend(active.values())
            active.clear()
            last_seen.clear()

        detections = detect_people(frame.image)
        for d in detections:
            d.frame_index = frame.index

        matched_track_ids = set()
        for det in detections:
            best_id, best_iou = None, 0.0
            for tid, track in active.items():
                if tid in matched_track_ids:
                    continue
                iou = _iou(track.boxes[-1], det)
                if iou > best_iou:
                    best_iou, best_id = iou, tid
            if best_id is not None and best_iou >= iou_threshold:
                active[best_id].boxes.append(det)
                last_seen[best_id] = frame.index
                matched_track_ids.add(best_id)
                continue

            # V2 gap bridging: no IOU match, but a coasting track's predicted
            # position may be close (player briefly occluded, box lost).
            best_id, best_dist = None, float("inf")
            det_cx, det_cy = det.x + det.w / 2, det.y + det.h / 2
            for tid, track in active.items():
                if tid in matched_track_ids:
                    continue
                px, py = _predicted_center(track)
                dist = ((det_cx - px) ** 2 + (det_cy - py) ** 2) ** 0.5
                if dist < best_dist:
                    best_dist, best_id = dist, tid
            reassoc_radius = max(det.w, det.h) * 1.5
            if best_id is not None and best_dist <= reassoc_radius:
                active[best_id].boxes.append(det)
                last_seen[best_id] = frame.index
                matched_track_ids.add(best_id)
            else:
                new_track = Track(track_id=next_id, boxes=[det])
                active[next_id] = new_track
                last_seen[next_id] = frame.index
                matched_track_ids.add(next_id)
                next_id += 1

        stale = [tid for tid, seen in last_seen.items() if frame.index - seen > max_missed_frames]
        for tid in stale:
            finished.append(active.pop(tid))
            last_seen.pop(tid)

    finished.extend(active.values())
    finished = _merge_broken_tracks(finished, cut_frames)

    # Drop very short-lived spurious tracks (noise), keep genuine player tracks.
    return [t for t in finished if len(t.boxes) >= 3]


def _merge_broken_tracks(tracks: List[Track], cut_frames: set, max_gap_frames: int = 20) -> List[Track]:
    """Post-pass: re-link a track that died with one that starts shortly after
    at a nearby predicted position (longer occlusion than live coasting covers).
    Never merges across a camera cut."""
    tracks = sorted(tracks, key=lambda t: t.first_frame)
    merged: List[Track] = []
    consumed = set()

    for i, track in enumerate(tracks):
        if i in consumed:
            continue
        current = track
        changed = True
        while changed:
            changed = False
            for j in range(i + 1, len(tracks)):
                if j in consumed:
                    continue
                candidate = tracks[j]
                gap = candidate.first_frame - current.last_frame
                if gap < 1 or gap > max_gap_frames:
                    continue
                if any(current.last_frame < cf <= candidate.first_frame for cf in cut_frames):
                    continue
                px, py = _predicted_center(current)
                cb = candidate.boxes[0]
                dist = ((cb.x + cb.w / 2 - px) ** 2 + (cb.y + cb.h / 2 - py) ** 2) ** 0.5
                if dist <= max(cb.w, cb.h) * 2.0:
                    current.boxes.extend(candidate.boxes)
                    consumed.add(j)
                    changed = True
                    break
        merged.append(current)

    return merged
