"""Locally-generated badminton test clips covering the recording conditions
the pipeline claims to handle.

Why synthetic: the project rules forbid scraping or downloading copyrighted
match footage, and no licensed corpus is bundled with the repo. These clips
are generated here, so they are lawful to use and fully reproducible.

What they CAN validate: upload handling, the video-quality gate (resolution,
frame rate, lighting, blur, shake, cuts), court detection and calibration,
rally segmentation plumbing, error handling, latency, and whether the UI
communicates uncertainty.

What they CANNOT validate: pose estimation, player tracking, and stroke
recognition. Those depend on MediaPipe/HOG finding real human bodies, which
coloured rectangles do not provide. Those rows are reported as NOT TESTED
rather than guessed at — see the report's "Known limitations".
"""
import math
from pathlib import Path

import cv2
import numpy as np

W, H = 1280, 720
FPS = 30


def _court(img, margin_x=150, margin_y=90, line=(255, 255, 255), thickness=3):
    """Draw a badminton-like court with the main lines."""
    h, w = img.shape[:2]
    mx = int(w * margin_x / W)
    my = int(h * margin_y / H)
    cv2.rectangle(img, (mx, my), (w - mx, h - my), line, thickness)
    cv2.line(img, (mx, h // 2), (w - mx, h // 2), line, thickness)          # net
    cv2.line(img, (w // 2, my), (w // 2, h - my), line, max(1, thickness - 1))  # centre
    cv2.line(img, (mx, my + (h // 2 - my) // 2), (w - mx, my + (h // 2 - my) // 2), line, 2)
    cv2.line(img, (mx, h // 2 + (h - my - h // 2) // 2),
             (w - mx, h // 2 + (h - my - h // 2) // 2), line, 2)
    return img


def _player(img, cx, cy, colour, scale=1.0):
    """A crude humanoid: torso, head, limbs. Enough for motion energy; NOT
    enough for real pose estimation (documented limitation)."""
    t = int(60 * scale)
    cv2.rectangle(img, (cx - t // 2, cy - t), (cx + t // 2, cy + t), colour, -1)
    cv2.circle(img, (cx, cy - t - int(18 * scale)), int(16 * scale), (225, 195, 170), -1)
    cv2.line(img, (cx, cy - t // 2), (cx + int(45 * scale), cy - int(55 * scale)), (225, 195, 170), int(9 * scale))
    cv2.line(img, (cx, cy - t // 2), (cx - int(38 * scale), cy - int(10 * scale)), (225, 195, 170), int(9 * scale))
    cv2.line(img, (cx - t // 4, cy + t), (cx - int(22 * scale), cy + int(70 * scale)), colour, int(11 * scale))
    cv2.line(img, (cx + t // 4, cy + t), (cx + int(22 * scale), cy + int(70 * scale)), colour, int(11 * scale))
    return img


def _shuttle(img, x, y, r=5):
    cv2.circle(img, (int(x), int(y)), r, (255, 255, 255), -1)
    return img


def _write(path, frames, fps=FPS, size=(W, H)):
    vw = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    for f in frames:
        vw.write(f)
    vw.release()
    return path


def _base_frames(n, w=W, h=H, players=2, rally_gap=True):
    """Rally-like motion with quiet gaps between rallies."""
    frames = []
    for i in range(n):
        t = i / FPS
        img = np.full((h, w, 3), (45, 105, 45), dtype=np.uint8)
        _court(img)
        active = (not rally_gap) or (int(t) % 8) < 6   # ~2s quiet every 8s
        amp = 200 if active else 8
        p1x = int(w * 0.35 + amp * math.sin(t * 2.2))
        p2x = int(w * 0.62 + amp * math.sin(t * 1.7 + 1.2))
        _player(img, p1x, int(h * 0.72), (40, 40, 190))
        _player(img, p2x, int(h * 0.30), (190, 60, 40), scale=0.8)
        if players == 4:
            _player(img, int(w * 0.20 + amp * 0.5 * math.cos(t * 1.9)), int(h * 0.80), (60, 60, 210), 0.95)
            _player(img, int(w * 0.78 + amp * 0.5 * math.cos(t * 1.4)), int(h * 0.24), (210, 90, 60), 0.75)
        if active:
            sx = w * 0.5 + (w * 0.3) * math.sin(t * 4.4)
            sy = h * 0.5 - abs(math.sin(t * 8.8)) * h * 0.25
            _shuttle(img, sx, sy)
        frames.append(img)
    return frames


# --- scenario builders ------------------------------------------------------

def scenario_singles_rally(path):
    return _write(path, _base_frames(FPS * 12))


def scenario_doubles_rally(path):
    return _write(path, _base_frames(FPS * 12, players=4))


def scenario_low_light(path):
    frames = [(f * 0.18).astype(np.uint8) for f in _base_frames(FPS * 8)]
    return _write(path, frames)


def scenario_motion_blur(path):
    frames = [cv2.GaussianBlur(f, (21, 21), 0) for f in _base_frames(FPS * 8)]
    return _write(path, frames)


def scenario_camera_shake(path):
    out = []
    for i, f in enumerate(_base_frames(FPS * 8)):
        dx, dy = int(14 * math.sin(i * 1.7)), int(11 * math.cos(i * 2.3))
        M = np.float32([[1, 0, dx], [0, 1, dy]])
        out.append(cv2.warpAffine(f, M, (W, H), borderMode=cv2.BORDER_REPLICATE))
    return _write(path, out)


def scenario_camera_cuts(path):
    a = _base_frames(FPS * 4)
    b = [np.full((H, W, 3), (140, 40, 40), dtype=np.uint8) for _ in range(FPS * 2)]
    c = _base_frames(FPS * 4)
    return _write(path, a + b + c)


def scenario_partial_court(path):
    """Camera too tight: only half the court in frame."""
    frames = [f[:, : W // 2] for f in _base_frames(FPS * 8)]
    frames = [cv2.resize(f, (W, H)) for f in frames]
    return _write(path, frames)


def scenario_portrait_phone(path):
    frames = [cv2.resize(f, (720, 1280)) for f in _base_frames(FPS * 8)]
    return _write(path, frames, size=(720, 1280))


def scenario_landscape_phone(path):
    frames = [cv2.resize(f, (854, 480)) for f in _base_frames(FPS * 8, w=854, h=480)]
    return _write(path, frames, size=(854, 480))


def scenario_low_resolution(path):
    frames = [cv2.resize(f, (426, 240)) for f in _base_frames(FPS * 8, w=426, h=240)]
    return _write(path, frames, size=(426, 240))


def scenario_low_framerate(path):
    return _write(path, _base_frames(60), fps=8)


def scenario_multiple_people(path):
    """Players plus spectators/umpire in frame."""
    out = []
    for i, f in enumerate(_base_frames(FPS * 8)):
        for k, x in enumerate((60, 120, W - 70, W - 130)):
            _player(f, x, int(H * (0.45 + 0.03 * k)), (110, 110, 110), 0.55)
        out.append(f)
    return _write(path, out)


def scenario_occlusion(path):
    """Players cross and overlap repeatedly."""
    frames = []
    for i in range(FPS * 8):
        t = i / FPS
        img = np.full((H, W, 3), (45, 105, 45), dtype=np.uint8)
        _court(img)
        x = int(W * 0.5 + 220 * math.sin(t * 2.0))
        y = int(W * 0.5 - 220 * math.sin(t * 2.0))
        _player(img, x, int(H * 0.6), (40, 40, 190))
        _player(img, y, int(H * 0.6), (190, 60, 40))
        frames.append(img)
    return _write(path, frames)


def scenario_no_court(path):
    """Not a badminton court at all — the gate should notice."""
    frames = []
    for i in range(FPS * 6):
        img = np.full((H, W, 3), (30, 30, 30), dtype=np.uint8)
        cv2.circle(img, (W // 2 + i, H // 2), 40, (200, 200, 200), -1)
        frames.append(img)
    return _write(path, frames)


SCENARIOS = {
    "singles_rally": (scenario_singles_rally, "Singles rally, tripod side view, good light"),
    "doubles_rally": (scenario_doubles_rally, "Doubles rally, 4 players"),
    "low_light": (scenario_low_light, "Poorly lit hall"),
    "motion_blur": (scenario_motion_blur, "Heavy motion blur / soft focus"),
    "camera_shake": (scenario_camera_shake, "Handheld, shaky camera"),
    "camera_cuts": (scenario_camera_cuts, "Edited footage with a hard scene cut"),
    "partial_court": (scenario_partial_court, "Court only partially visible"),
    "portrait_phone": (scenario_portrait_phone, "Portrait phone video 720x1280"),
    "landscape_phone": (scenario_landscape_phone, "Landscape phone video 854x480"),
    "low_resolution": (scenario_low_resolution, "426x240 - below shuttle threshold"),
    "low_framerate": (scenario_low_framerate, "8 fps source"),
    "multiple_people": (scenario_multiple_people, "Players plus spectators in frame"),
    "occlusion": (scenario_occlusion, "Players repeatedly crossing/occluding"),
    "no_court": (scenario_no_court, "Non-badminton footage"),
}


def build_all(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    built = {}
    for name, (fn, desc) in SCENARIOS.items():
        p = out_dir / f"{name}.mp4"
        if not p.exists():
            fn(p)
        built[name] = {"path": p, "description": desc}
    return built


if __name__ == "__main__":
    import sys
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/bc-scenarios")
    for name, info in build_all(target).items():
        print(f"{name:18} {info['path'].stat().st_size:>9,} bytes  {info['description']}")
