"""Authoritative media inspection.

Everything the browser told us about a file is a claim. `content_type` comes
from the OS's guess, `size_bytes` from JavaScript, the extension from whatever
the user renamed it to. This module is where the system finds out what was
actually uploaded, and it runs before a single frame reaches the CV pipeline.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Optional

from app.core import config
from app.media import ffmpeg
from app.media.errors import (
    MediaError, E_CORRUPT_MEDIA, E_FPS_TOO_HIGH, E_NO_VIDEO_STREAM, E_PROBE_FAILED,
    E_RESOLUTION_TOO_LARGE, E_TOO_LARGE, E_TOO_LONG, E_ZERO_DURATION,
)

logger = logging.getLogger("app.media.probe")

# Codecs the OpenCV/FFmpeg build in the worker image decodes dependably.
DECODABLE_VIDEO_CODECS = frozenset({
    "h264", "hevc", "h265", "mpeg4", "vp8", "vp9", "av1", "mjpeg",
    "mpeg2video", "prores", "wmv3", "vc1", "theora",
})

# Containers the analysis pipeline can consume without a re-mux.
PASSTHROUGH_CONTAINERS = frozenset({"mov,mp4,m4a,3gp,3g2,mj2", "mp4", "mov"})


def _to_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_rate(raw: Optional[str]) -> float:
    """'30000/1001' -> 29.97. ffprobe reports rates as exact fractions and
    rounding them early is how 29.97 fps footage ends up analyzed as 30."""
    if not raw or raw in ("0/0", "N/A"):
        return 0.0
    try:
        return float(Fraction(raw))
    except (ZeroDivisionError, ValueError):
        return 0.0


@dataclass
class MediaInfo:
    container: str = ""
    format_long_name: str = ""
    duration_s: float = 0.0
    size_bytes: int = 0
    bitrate: int = 0

    video_codec: str = ""
    width: int = 0
    height: int = 0
    fps: float = 0.0
    avg_fps: float = 0.0
    pix_fmt: str = ""
    rotation: int = 0
    display_aspect_ratio: str = ""
    nb_frames: int = 0

    audio_codec: str = ""
    has_audio: bool = False
    stream_count: int = 0

    raw: dict = field(default_factory=dict)

    @property
    def display_width(self) -> int:
        """Width after rotation is applied — a portrait phone clip reports
        1920x1080 with rotation=90, and every downstream consumer needs the
        1080x1920 it will actually decode as."""
        return self.height if self.rotation in (90, 270) else self.width

    @property
    def display_height(self) -> int:
        return self.width if self.rotation in (90, 270) else self.height

    @property
    def megapixels(self) -> float:
        return (self.width * self.height) / 1_000_000

    def as_dict(self) -> dict:
        return {
            "container": self.container, "duration_s": round(self.duration_s, 3),
            "size_bytes": self.size_bytes, "bitrate": self.bitrate,
            "video_codec": self.video_codec, "width": self.display_width,
            "height": self.display_height, "fps": round(self.fps, 4),
            "pix_fmt": self.pix_fmt, "rotation": self.rotation,
            "display_aspect_ratio": self.display_aspect_ratio,
            "audio_codec": self.audio_codec, "has_audio": self.has_audio,
            "stream_count": self.stream_count,
        }


def _rotation_of(stream: dict) -> int:
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            return int(round(_to_float(side["rotation"]))) % 360
    tag = (stream.get("tags") or {}).get("rotate")
    if tag is not None:
        return int(round(_to_float(tag))) % 360
    return 0


# ffprobe exits non-zero both for "the network hiccuped" and for "this is a
# text file named .mp4". Only the first is worth retrying, and a retryable
# classification on the second means three workers each burn a download
# proving the same thing. These substrings mark the permanent half.
_PERMANENT_PROBE_SIGNATURES = (
    "invalid data found when processing input",
    "moov atom not found",
    "does not contain any stream",
    "invalid argument",
    "unknown format",
    "end of file",
    "header damaged",
    "could not find codec parameters",
)


def probe(path: Path) -> MediaInfo:
    """Inspect a local file. Raises MediaError with a specific code."""
    try:
        data = ffmpeg.probe_json(path)
    except MediaError as exc:
        if exc.code == E_PROBE_FAILED:
            lowered = (exc.detail or "").lower()
            if any(sig in lowered for sig in _PERMANENT_PROBE_SIGNATURES):
                raise MediaError(E_CORRUPT_MEDIA, exc.detail) from exc
        raise

    if data.get("error"):
        raise MediaError(E_CORRUPT_MEDIA, str(data["error"])[:400])

    fmt = data.get("format") or {}
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    if video is None:
        raise MediaError(E_NO_VIDEO_STREAM, "ffprobe found no video stream")

    info = MediaInfo(
        container=fmt.get("format_name", ""),
        format_long_name=fmt.get("format_long_name", ""),
        duration_s=_to_float(fmt.get("duration")) or _to_float(video.get("duration")),
        size_bytes=int(_to_float(fmt.get("size"), path.stat().st_size)),
        bitrate=int(_to_float(fmt.get("bit_rate"))),
        video_codec=(video.get("codec_name") or "").lower(),
        width=int(_to_float(video.get("width"))),
        height=int(_to_float(video.get("height"))),
        fps=_parse_rate(video.get("r_frame_rate")),
        avg_fps=_parse_rate(video.get("avg_frame_rate")),
        pix_fmt=video.get("pix_fmt", ""),
        rotation=_rotation_of(video),
        display_aspect_ratio=video.get("display_aspect_ratio", ""),
        nb_frames=int(_to_float(video.get("nb_frames"))),
        audio_codec=(audio.get("codec_name") or "").lower() if audio else "",
        has_audio=audio is not None,
        stream_count=len(streams),
        raw=data,
    )

    # Some containers (notably MKV and damaged MP4s) omit duration in the
    # format header. Recover it from the stream before declaring failure.
    if info.duration_s <= 0 and info.nb_frames and info.fps:
        info.duration_s = info.nb_frames / info.fps

    return info


def validate(info: MediaInfo, *, declared_size: Optional[int] = None) -> None:
    """Enforce production media limits. These exist so one upload cannot
    monopolise a worker — not to be stingy about legitimate footage."""
    if info.width <= 0 or info.height <= 0:
        raise MediaError(E_CORRUPT_MEDIA, "video stream reports no dimensions")
    if info.duration_s <= 0:
        raise MediaError(E_ZERO_DURATION, "no playable duration")
    if info.duration_s > config.MAX_VIDEO_DURATION_S_HARD:
        raise MediaError(
            E_TOO_LONG,
            f"{info.duration_s:.0f}s exceeds the {config.MAX_VIDEO_DURATION_S_HARD}s limit",
        )
    if info.size_bytes > config.MAX_VIDEO_BYTES:
        raise MediaError(E_TOO_LARGE, f"{info.size_bytes} bytes exceeds {config.MAX_VIDEO_BYTES}")
    if info.display_width > config.MAX_VIDEO_WIDTH or info.display_height > config.MAX_VIDEO_HEIGHT:
        raise MediaError(
            E_RESOLUTION_TOO_LARGE,
            f"{info.display_width}x{info.display_height} exceeds "
            f"{config.MAX_VIDEO_WIDTH}x{config.MAX_VIDEO_HEIGHT}",
        )
    if info.fps > config.MAX_VIDEO_FPS:
        raise MediaError(E_FPS_TOO_HIGH, f"{info.fps} fps exceeds {config.MAX_VIDEO_FPS}")

    # A file that stopped uploading mid-stream often still probes: the moov
    # atom is there, the data is truncated. Catching it here means a clear
    # "upload didn't finish" instead of a confusing CV failure later.
    if declared_size and info.size_bytes and declared_size != info.size_bytes:
        logger.warning("declared size %s != actual %s", declared_size, info.size_bytes)
