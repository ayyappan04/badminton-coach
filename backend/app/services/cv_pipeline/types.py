"""Shared data contracts passed between CV pipeline stages."""
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

import numpy as np


@dataclass
class Frame:
    index: int
    timestamp_s: float
    image: np.ndarray  # BGR, as read by OpenCV


@dataclass
class CalibrationResult:
    method: str  # "auto_hough" | "user_assisted" | "manual" | "fallback_full_frame"
    court_corners_px: List[List[float]]  # 4 points, pixel space, TL,TR,BR,BL order
    homography: Optional[np.ndarray]  # 3x3 pixel->court-meters
    confidence: float
    notes: str = ""
    limitations: List[str] = field(default_factory=list)


@dataclass
class DetectionBox:
    frame_index: int
    x: float
    y: float
    w: float
    h: float
    confidence: float


@dataclass
class Track:
    track_id: int
    boxes: List[DetectionBox]
    role: str = "unassigned"

    @property
    def first_frame(self) -> int:
        return self.boxes[0].frame_index if self.boxes else 0

    @property
    def last_frame(self) -> int:
        return self.boxes[-1].frame_index if self.boxes else 0

    @property
    def mean_confidence(self) -> float:
        if not self.boxes:
            return 0.0
        return sum(b.confidence for b in self.boxes) / len(self.boxes)


@dataclass
class PoseSample:
    track_id: int
    frame_index: int
    timestamp_s: float
    landmarks: List[Dict[str, float]]  # 33 entries: {name, x, y, z, visibility} in crop-normalized coords mapped back to frame-normalized
    confidence: float


@dataclass
class ShuttlePoint:
    frame_index: int
    timestamp_s: float
    x_px: float
    y_px: float
    confidence: float


@dataclass
class RallySegment:
    rally_index: int
    start_frame: int
    end_frame: int
    start_timestamp_s: float
    end_timestamp_s: float
    confidence: float


@dataclass
class ShotEvent:
    track_id: int
    rally_index: int
    frame_index: int
    timestamp_s: float
    shot_type: str
    side: str
    contact_height: str
    intent: str
    outcome: str
    confidence: float


@dataclass
class VideoMeta:
    fps: float
    frame_count: int
    width: int
    height: int
    duration_s: float


@dataclass
class PipelineResult:
    meta: VideoMeta
    calibration: CalibrationResult
    tracks: List[Track]
    poses: List[PoseSample]
    shuttle_points: List[ShuttlePoint]
    rallies: List[RallySegment]
    shots: List[ShotEvent]
    biomechanics: Dict[str, Any]
    tactics: Dict[str, Any]
    limitations: List[str] = field(default_factory=list)
    quality: Optional[Dict[str, Any]] = None
    phases_by_rally: Dict[int, List[Dict[str, Any]]] = field(default_factory=dict)
