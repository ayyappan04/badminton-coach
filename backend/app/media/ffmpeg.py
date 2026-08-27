"""Controlled FFmpeg/FFprobe invocation.

Every rule here exists because the input is a file a stranger uploaded:

* Argument arrays only. There is no shell, so there is nothing for a filename
  or a metadata string to be interpolated into.
* Explicit `-nostdin`, so a malformed container can never leave ffmpeg waiting
  on a terminal that will never answer.
* A wall-clock timeout, so a stalled decode is killed rather than holding a
  worker forever.
* Bounded stderr capture. ffmpeg will happily emit hundreds of megabytes of
  warnings on a damaged file; we keep the tail.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Sequence

from app.core import config
from app.media.errors import (
    MediaError, E_FFMPEG_MISSING, E_PROBE_FAILED, E_TRANSCODE_FAILED, E_TRANSCODE_TIMEOUT,
)

logger = logging.getLogger("app.media.ffmpeg")

_LOG_TAIL_CHARS = 4000

#: Output containers this application writes. Anything else is a bug.
_MUXERS = {
    ".mp4": "mp4", ".m4v": "mp4", ".mov": "mov", ".webm": "webm",
    ".jpg": "image2", ".jpeg": "image2", ".png": "image2",
}


@lru_cache(maxsize=2)
def _resolve(name: str) -> str:
    """Find a binary: explicit env var, then PATH, then the pip-installed
    imageio-ffmpeg build. The last one keeps `pytest` meaningful on a machine
    with no system ffmpeg; production containers install the real thing."""
    override = config.FFMPEG_BIN if name == "ffmpeg" else config.FFPROBE_BIN
    if override and Path(override).exists():
        return override

    found = shutil.which(name)
    if found:
        return found

    # Dev fallback: a pip-installed static build. Present on a laptop without
    # Homebrew; absent (and unnecessary) in the container, which apt-installs
    # ffmpeg properly. Never reached in production because PATH resolves first.
    try:
        import static_ffmpeg.run as _sf
        for candidate in _sf.get_or_fetch_platform_executables_else_raise():
            if Path(candidate).name.startswith(name):
                return candidate
    except Exception:  # noqa: BLE001 — absence is the normal case, not an error
        pass

    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if name == "ffmpeg":
            return exe
        sibling = Path(exe).with_name("ffprobe")
        if sibling.exists():
            return str(sibling)
    except Exception:  # noqa: BLE001
        pass

    raise MediaError(E_FFMPEG_MISSING, f"{name} not found on PATH or via FFMPEG_BIN/FFPROBE_BIN")


def ffmpeg_bin() -> str:
    return _resolve("ffmpeg")


def ffprobe_bin() -> str:
    return _resolve("ffprobe")


def available() -> bool:
    try:
        _resolve("ffmpeg")
        return True
    except MediaError:
        return False


def _run(argv: Sequence[str], timeout_s: int, code_on_fail: str) -> subprocess.CompletedProcess:
    logger.debug("exec %s", " ".join(argv[:6]) + " ...")
    try:
        proc = subprocess.run(
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
            check=False,
            # Never inherit the parent's environment wholesale: ffmpeg reads
            # several env vars that change decoding behaviour.
            env={"PATH": os.environ.get("PATH", ""), "LC_ALL": "C"},
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaError(E_TRANSCODE_TIMEOUT, f"timed out after {timeout_s}s") from exc
    except OSError as exc:
        raise MediaError(code_on_fail, str(exc)) from exc

    if proc.returncode != 0:
        tail = (proc.stderr or b"").decode("utf-8", "replace")[-_LOG_TAIL_CHARS:]
        raise MediaError(code_on_fail, f"exit {proc.returncode}: {tail}")
    return proc


def probe_json(path: Path) -> dict:
    argv = [
        ffprobe_bin(), "-v", "error", "-hide_banner",
        "-print_format", "json", "-show_format", "-show_streams", "-show_error",
        str(path),
    ]
    proc = _run(argv, config.FFPROBE_TIMEOUT_S, E_PROBE_FAILED)
    try:
        return json.loads(proc.stdout.decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError as exc:
        raise MediaError(E_PROBE_FAILED, f"unparsable ffprobe output: {exc}") from exc


def transcode(argv_tail: List[str], *, src: Path, dest: Path,
              pre_input: Optional[List[str]] = None,
              timeout_s: Optional[int] = None) -> Path:
    """Run one ffmpeg conversion.

    Writes to a `.part` sibling and renames on success, so a killed worker can
    never leave a truncated file that looks like a finished asset.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".part")
    partial.unlink(missing_ok=True)

    # Writing to `foo.mp4.part` means ffmpeg can no longer infer the muxer
    # from the extension, so state it. Being explicit is better anyway: the
    # container is a decision, not something to leave to filename parsing.
    tail = list(argv_tail)
    if "-f" not in tail:
        muxer = _MUXERS.get(dest.suffix.lower())
        if muxer is None:
            raise MediaError(E_TRANSCODE_FAILED, f"no muxer mapped for {dest.suffix!r}")
        tail = ["-f", muxer, *tail]

    argv = [
        ffmpeg_bin(), "-nostdin", "-hide_banner", "-loglevel", "error",
        "-y",                      # explicit overwrite of our own temp file
        # `-ss` belongs before `-i` for frame grabs: it seeks the container
        # instead of decoding from zero, which on a 40-minute match is the
        # difference between milliseconds and minutes.
        *(pre_input or []),
        "-i", str(src),
        *tail,
        str(partial),
    ]
    try:
        _run(argv, timeout_s or config.FFMPEG_TIMEOUT_S, E_TRANSCODE_FAILED)
        if not partial.exists() or partial.stat().st_size == 0:
            raise MediaError(E_TRANSCODE_FAILED, "ffmpeg produced an empty file")
        partial.replace(dest)
        return dest
    except Exception:
        partial.unlink(missing_ok=True)
        raise
