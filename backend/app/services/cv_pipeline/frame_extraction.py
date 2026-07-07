from typing import Iterator, Tuple

import cv2

from app.services.cv_pipeline.types import Frame, VideoMeta


def read_video_meta(path: str) -> VideoMeta:
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {path}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 0.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()
    if fps <= 0:
        fps = 25.0  # sane fallback for malformed metadata
    duration_s = frame_count / fps if fps else 0.0
    return VideoMeta(fps=fps, frame_count=frame_count, width=width, height=height, duration_s=duration_s)


def iter_frames(path: str, sample_fps: float) -> Iterator[Frame]:
    """Yields frames sampled at approximately `sample_fps`, regardless of the
    source video's native frame rate."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {path}")
    native_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    step = max(1, round(native_fps / sample_fps)) if sample_fps > 0 else 1

    frame_index = 0
    kept_index = 0
    while True:
        ok, image = cap.read()
        if not ok:
            break
        if frame_index % step == 0:
            timestamp_s = frame_index / native_fps
            yield Frame(index=kept_index, timestamp_s=timestamp_s, image=image)
            kept_index += 1
        frame_index += 1
    cap.release()


def iter_frames_native(path: str) -> Iterator[Tuple[int, float, "cv2.Mat"]]:
    """Full-native-fps frame iterator, used by motion-sensitive stages
    (shuttle detection, rally segmentation) where downsampling would blur fast events."""
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise ValueError(f"Could not open video file: {path}")
    native_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_index = 0
    while True:
        ok, image = cap.read()
        if not ok:
            break
        yield frame_index, frame_index / native_fps, image
        frame_index += 1
    cap.release()
