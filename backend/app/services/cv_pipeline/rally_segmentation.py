"""Rally segmentation via player motion-energy troughs: sustained low
aggregate player movement is treated as "between rallies" (players resetting,
picking up shuttle, preparing to serve); sustained higher movement is treated
as active play. This is a simple, explainable heuristic — not a learned model
— and is the first thing to revisit if rally boundaries look off in testing.
"""
from typing import List, Dict

from app.services.cv_pipeline.types import Track, RallySegment

MIN_RALLY_DURATION_S = 1.5
MIN_GAP_DURATION_S = 1.2


def _motion_energy_by_frame(tracks: List[Track]) -> Dict[int, float]:
    positions_by_track: Dict[int, List] = {}
    for track in tracks:
        positions_by_track[track.track_id] = sorted(track.boxes, key=lambda b: b.frame_index)

    energy: Dict[int, float] = {}
    for track_id, boxes in positions_by_track.items():
        for a, b in zip(boxes, boxes[1:]):
            cx_a, cy_a = a.x + a.w / 2, a.y + a.h / 2
            cx_b, cy_b = b.x + b.w / 2, b.y + b.h / 2
            dist = ((cx_b - cx_a) ** 2 + (cy_b - cy_a) ** 2) ** 0.5
            energy[b.frame_index] = energy.get(b.frame_index, 0.0) + dist
    return energy


def segment_rallies(tracks: List[Track], fps_sampled: float, threshold_ratio: float = 0.35) -> List[RallySegment]:
    energy = _motion_energy_by_frame(tracks)
    if not energy:
        return []

    frame_indices = sorted(energy.keys())
    first, last = frame_indices[0], frame_indices[-1]
    raw = [energy.get(i, 0.0) for i in range(first, last + 1)]

    # V2: moving-average smoothing (~0.7s window) so a single quiet frame
    # mid-rally doesn't split it, then dual-threshold hysteresis so entering
    # and leaving a rally require different evidence levels.
    window = max(1, int(fps_sampled * 0.7))
    smoothed = []
    for i in range(len(raw)):
        lo, hi = max(0, i - window // 2), min(len(raw), i + window // 2 + 1)
        smoothed.append(sum(raw[lo:hi]) / (hi - lo))

    max_energy = max(smoothed) if smoothed else 0.0
    if max_energy == 0:
        return []
    t_high = max_energy * threshold_ratio
    t_low = max_energy * threshold_ratio * 0.5
    exit_patience = max(1, int(fps_sampled * 0.8))  # frames below t_low before the rally ends

    rallies: List[RallySegment] = []
    rally_index = 0
    start = None
    below_count = 0
    for i, value in enumerate(smoothed):
        frame_no = first + i
        if start is None:
            if value >= t_high:
                start = frame_no
                below_count = 0
        else:
            if value < t_low:
                below_count += 1
                if below_count >= exit_patience:
                    end = frame_no - exit_patience
                    duration_s = (end - start) / fps_sampled
                    if duration_s >= MIN_RALLY_DURATION_S:
                        rallies.append(RallySegment(
                            rally_index=rally_index, start_frame=start, end_frame=end,
                            start_timestamp_s=start / fps_sampled, end_timestamp_s=end / fps_sampled,
                            confidence=0.6,
                        ))
                        rally_index += 1
                    start = None
                    below_count = 0
            else:
                below_count = 0
    if start is not None:
        end = last
        duration_s = (end - start) / fps_sampled
        if duration_s >= MIN_RALLY_DURATION_S:
            rallies.append(RallySegment(
                rally_index=rally_index, start_frame=start, end_frame=end,
                start_timestamp_s=start / fps_sampled, end_timestamp_s=end / fps_sampled,
                confidence=0.6,
            ))

    # Merge rallies separated by very short gaps (likely a single continuous rally
    # briefly dipping below the motion threshold).
    merged: List[RallySegment] = []
    for r in rallies:
        if merged and (r.start_timestamp_s - merged[-1].end_timestamp_s) < MIN_GAP_DURATION_S:
            prev = merged.pop()
            merged.append(RallySegment(
                rally_index=prev.rally_index, start_frame=prev.start_frame, end_frame=r.end_frame,
                start_timestamp_s=prev.start_timestamp_s, end_timestamp_s=r.end_timestamp_s,
                confidence=min(prev.confidence, r.confidence),
            ))
        else:
            merged.append(r)

    for idx, r in enumerate(merged):
        r.rally_index = idx

    return merged
