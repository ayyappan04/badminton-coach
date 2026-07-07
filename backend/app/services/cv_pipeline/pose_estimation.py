"""Per-player body-landmark estimation using MediaPipe Pose, run against a
padded crop around each tracked person's bounding box per frame.

Presented to the product layer strictly as video-based estimates — see
docs/CV_PIPELINE.md and the biomechanics module for how these feed
joint-angle/stability approximations. Not a clinical measurement.
"""
from typing import List, Dict

import cv2
import mediapipe as mp
import numpy as np

from app.services.cv_pipeline.types import Frame, Track, PoseSample

_LANDMARK_NAMES = [l.name.lower() for l in mp.solutions.pose.PoseLandmark]


def _pad_box(x, y, w, h, frame_w, frame_h, pad_ratio=0.25):
    pad_x, pad_y = w * pad_ratio, h * pad_ratio
    x0 = max(0, int(x - pad_x))
    y0 = max(0, int(y - pad_y))
    x1 = min(frame_w, int(x + w + pad_x))
    y1 = min(frame_h, int(y + h + pad_y))
    return x0, y0, x1, y1


def estimate_poses(frames: List[Frame], tracks: List[Track]) -> List[PoseSample]:
    if not tracks:
        return []

    boxes_by_frame: Dict[int, List] = {}
    for track in tracks:
        for box in track.boxes:
            boxes_by_frame.setdefault(box.frame_index, []).append((track.track_id, box))

    samples: List[PoseSample] = []
    pose_detector = mp.solutions.pose.Pose(
        static_image_mode=True, model_complexity=1, min_detection_confidence=0.3
    )
    try:
        for frame in frames:
            entries = boxes_by_frame.get(frame.index)
            if not entries:
                continue
            frame_h, frame_w = frame.image.shape[:2]
            for track_id, box in entries:
                x0, y0, x1, y1 = _pad_box(box.x, box.y, box.w, box.h, frame_w, frame_h)
                if x1 <= x0 or y1 <= y0:
                    continue
                crop = frame.image[y0:y1, x0:x1]
                if crop.size == 0:
                    continue
                rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
                result = pose_detector.process(rgb)
                if not result.pose_landmarks:
                    continue

                crop_h, crop_w = crop.shape[:2]
                landmarks = []
                visibilities = []
                for name, lm in zip(_LANDMARK_NAMES, result.pose_landmarks.landmark):
                    # map crop-normalized coords back to full-frame-normalized coords
                    px = (lm.x * crop_w + x0) / frame_w
                    py = (lm.y * crop_h + y0) / frame_h
                    landmarks.append({"name": name, "x": px, "y": py, "z": lm.z, "visibility": lm.visibility})
                    visibilities.append(lm.visibility)

                confidence = float(np.mean(visibilities)) if visibilities else 0.0
                samples.append(PoseSample(
                    track_id=track_id, frame_index=frame.index, timestamp_s=frame.timestamp_s,
                    landmarks=landmarks, confidence=confidence,
                ))
    finally:
        pose_detector.close()

    return samples
