"""Media normalization: turn an arbitrary phone recording into assets the rest
of the system can rely on.

Two outputs, deliberately not one.

The ANALYSIS proxy exists so the CV pipeline sees a predictable stream. Its
settings are conservative to the point of looking wasteful — 1080p, up to 60
fps, CRF 18 — and that is the point. A badminton shuttle occupies a handful of
pixels while travelling faster than any other racket-sport projectile, and
limbs at contact are pure motion blur. Compress that the way you would
compress a talking-head video and the shuttle-detection stage stops finding a
shuttle. The scores would still be produced. They would just be wrong, which
is worse than absent.

The PLAYBACK proxy is the opposite trade: 720p, CRF 26, faststart, AAC. It is
what a browser actually streams, so a user rewatching a rally twelve times
does not pull the 4 GB original twelve times.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from app.core import config
from app.media import ffmpeg
from app.media.errors import MediaError, E_TRANSCODE_FAILED
from app.media.probe import DECODABLE_VIDEO_CODECS, MediaInfo, PASSTHROUGH_CONTAINERS, probe
from app.storage.paths import MEDIA_TRANSFORM_VERSION

logger = logging.getLogger("app.media.normalize")


def _even(value: int) -> int:
    """yuv420p subsamples chroma 2x2, so both dimensions must be even. Odd
    values make ffmpeg fail with a filter error rather than round for you."""
    return max(2, int(value) // 2 * 2)


def fit_within(width: int, height: int, max_w: int, max_h: int) -> tuple[int, int]:
    """Scale down preserving aspect ratio. Never scales up: a 480p club
    recording stays 480p rather than being interpolated into a bigger file
    with no more information in it."""
    if width <= 0 or height <= 0:
        return width, height
    if width <= max_w and height <= max_h:
        return _even(width), _even(height)
    scale = min(max_w / width, max_h / height)
    return _even(round(width * scale)), _even(round(height * scale))


@dataclass
class NormalizationPlan:
    """The decision, separated from the doing, so it can be asserted on in a
    test and stored as provenance on the analysis run."""
    profile: str                       # "analysis" | "playback"
    passthrough: bool
    target_width: int
    target_height: int
    target_fps: Optional[float]
    codec: str
    crf: int
    preset: str
    strip_audio: bool
    reason: str
    transform_version: str = MEDIA_TRANSFORM_VERSION

    def as_dict(self) -> dict:
        return {
            "profile": self.profile, "passthrough": self.passthrough,
            "width": self.target_width, "height": self.target_height,
            "fps": self.target_fps, "codec": self.codec, "crf": self.crf,
            "preset": self.preset, "strip_audio": self.strip_audio,
            "reason": self.reason, "transform_version": self.transform_version,
        }


def plan_analysis(info: MediaInfo) -> NormalizationPlan:
    w, h = fit_within(info.display_width, info.display_height,
                      config.MAX_ANALYSIS_WIDTH, config.MAX_ANALYSIS_HEIGHT)
    fps = None
    if info.fps and info.fps > config.MAX_ANALYSIS_FPS_OUT:
        fps = config.MAX_ANALYSIS_FPS_OUT

    already_fine = (
        config.ALLOW_ANALYSIS_PASSTHROUGH
        and info.container in PASSTHROUGH_CONTAINERS
        and info.video_codec == "h264"
        and info.pix_fmt in ("yuv420p", "yuvj420p")
        and info.rotation == 0
        and (w, h) == (info.display_width, info.display_height)
        and fps is None
    )
    if already_fine:
        # Remux only: same bitstream, corrected container flags. No generation
        # loss, and a 4 GB file finishes in seconds instead of an hour.
        return NormalizationPlan(
            profile="analysis", passthrough=True, target_width=w, target_height=h,
            target_fps=None, codec="copy", crf=0, preset="", strip_audio=True,
            reason="source already H.264/yuv420p within the analysis envelope; remuxed with faststart",
        )

    reasons: List[str] = []
    if info.video_codec != "h264":
        reasons.append(f"codec {info.video_codec or 'unknown'}")
    if info.rotation:
        reasons.append(f"rotation {info.rotation}°")
    if (w, h) != (info.display_width, info.display_height):
        reasons.append(f"{info.display_width}x{info.display_height} -> {w}x{h}")
    if fps:
        reasons.append(f"{info.fps:.2f} -> {fps:.0f} fps")
    if info.container not in PASSTHROUGH_CONTAINERS:
        reasons.append(f"container {info.container}")
    if info.pix_fmt not in ("yuv420p", "yuvj420p"):
        reasons.append(f"pix_fmt {info.pix_fmt or 'unknown'}")

    return NormalizationPlan(
        profile="analysis", passthrough=False, target_width=w, target_height=h,
        target_fps=fps, codec=config.ANALYSIS_CODEC, crf=config.ANALYSIS_CRF,
        preset=config.ANALYSIS_PRESET, strip_audio=True,
        reason="; ".join(reasons) or "normalized to the analysis profile",
    )


def plan_playback(info: MediaInfo) -> NormalizationPlan:
    w, h = fit_within(info.display_width, info.display_height,
                      config.PLAYBACK_MAX_WIDTH, config.PLAYBACK_MAX_HEIGHT)
    fps = config.PLAYBACK_MAX_FPS if info.fps and info.fps > config.PLAYBACK_MAX_FPS else None
    return NormalizationPlan(
        profile="playback", passthrough=False, target_width=w, target_height=h,
        target_fps=fps, codec=config.PLAYBACK_CODEC, crf=config.PLAYBACK_CRF,
        preset=config.PLAYBACK_PRESET,
        strip_audio=(config.PLAYBACK_AUDIO == "none"),
        reason=f"browser playback proxy at {w}x{h}",
    )


def _argv_for(plan: NormalizationPlan) -> List[str]:
    if plan.passthrough:
        return ["-map", "0:v:0", "-an", "-c:v", "copy", "-movflags", "+faststart"]

    argv: List[str] = ["-map", "0:v:0"]
    filters = [f"scale={plan.target_width}:{plan.target_height}:flags=lanczos"]
    if plan.target_fps:
        # The fps filter resamples against presentation timestamps, so the
        # output stays in sync with the source clock. Setting -r instead would
        # renumber frames and quietly shift every shot timestamp we report.
        filters.append(f"fps={plan.target_fps}")
    argv += ["-vf", ",".join(filters)]
    argv += [
        "-c:v", plan.codec, "-preset", plan.preset, "-crf", str(plan.crf),
        "-pix_fmt", "yuv420p",
        # Rotation metadata has already been baked in by ffmpeg's autorotate;
        # clearing the tag stops players from applying it a second time.
        "-metadata:s:v:0", "rotate=0",
        "-movflags", "+faststart",
    ]
    if plan.strip_audio:
        argv += ["-an"]
    else:
        argv += ["-map", "0:a:0?", "-c:a", config.PLAYBACK_AUDIO, "-b:a", "128k", "-ac", "2"]
    return argv


def run_plan(plan: NormalizationPlan, src: Path, dest: Path,
             timeout_s: Optional[int] = None) -> MediaInfo:
    """Execute a plan and probe the result.

    The output is probed rather than assumed: a transcode that exits 0 having
    written two seconds of a forty-minute match is a real failure mode, and it
    is invisible unless someone measures.
    """
    ffmpeg.transcode(_argv_for(plan), src=src, dest=dest, timeout_s=timeout_s)
    out = probe(dest)
    if out.duration_s <= 0:
        raise MediaError(E_TRANSCODE_FAILED, f"{plan.profile} proxy has no duration", stage=plan.profile)
    return out


def make_analysis_proxy(info: MediaInfo, src: Path, dest: Path) -> tuple[MediaInfo, NormalizationPlan]:
    plan = plan_analysis(info)
    logger.info("analysis proxy: %s", plan.reason)
    try:
        return run_plan(plan, src, dest), plan
    except MediaError:
        if not plan.passthrough:
            raise
        # A stream copy can fail on containers whose bitstream needs filtering
        # (Annex-B H.264 in MPEG-TS, for one). Fall back to a real encode
        # rather than failing the upload over an optimisation.
        logger.warning("passthrough remux failed; falling back to a full encode")
        forced = plan_analysis(info)
        forced.passthrough = False
        forced.codec = config.ANALYSIS_CODEC
        forced.crf = config.ANALYSIS_CRF
        forced.preset = config.ANALYSIS_PRESET
        forced.reason = "passthrough remux failed; re-encoded"
        return run_plan(forced, src, dest), forced


def make_playback_proxy(info: MediaInfo, src: Path, dest: Path) -> tuple[MediaInfo, NormalizationPlan]:
    plan = plan_playback(info)
    return run_plan(plan, src, dest), plan


def _grab_frame(src: Path, dest: Path, at_s: float, width: int) -> Path:
    return ffmpeg.transcode(
        ["-frames:v", "1", "-vf", f"scale={_even(width)}:-2:flags=lanczos",
         "-q:v", "3", "-f", "image2"],
        src=src, dest=dest,
        pre_input=["-ss", f"{max(0.0, at_s):.3f}"],
        timeout_s=120,
    )


def make_poster_and_thumbnail(info: MediaInfo, src: Path, poster: Path,
                              thumbnail: Path) -> tuple[Path, Path]:
    """Two stills so the match library never loads a video to draw a card.

    Sampled at 10% in rather than at frame zero: the first frame of a match
    recording is reliably somebody's hand covering the lens.
    """
    at = min(max(info.duration_s * 0.1, 0.5), max(info.duration_s - 0.2, 0.5))
    _grab_frame(src, poster, at, min(config.PLAYBACK_MAX_WIDTH, info.display_width or 1280))
    _grab_frame(src, thumbnail, at, 480)
    return poster, thumbnail
