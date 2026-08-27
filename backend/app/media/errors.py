"""Media failures carry three separate things, because three different
audiences need them: a machine-readable code for retry logic, a safe sentence
for the user, and the raw detail for the server log."""
from __future__ import annotations

from typing import Optional

# Permanent — retrying the identical input cannot help.
E_NO_VIDEO_STREAM = "no_video_stream"
E_CORRUPT_MEDIA = "corrupt_media"
E_UNSUPPORTED_CODEC = "unsupported_codec"
E_TOO_LONG = "video_too_long"
E_TOO_LARGE = "video_too_large"
E_RESOLUTION_TOO_LARGE = "resolution_too_large"
E_FPS_TOO_HIGH = "fps_too_high"
E_ZERO_DURATION = "zero_duration"
E_OBJECT_MISSING = "source_object_missing"
E_SIZE_MISMATCH = "declared_size_mismatch"

# Transient — the same input may well succeed on a later attempt.
E_PROBE_FAILED = "probe_failed"
E_TRANSCODE_FAILED = "transcode_failed"
E_TRANSCODE_TIMEOUT = "transcode_timeout"
E_FFMPEG_MISSING = "ffmpeg_unavailable"
E_STORAGE_UNAVAILABLE = "storage_unavailable"
E_PIPELINE_FAILED = "pipeline_failed"
E_INTERNAL = "internal_error"

RETRYABLE = frozenset({
    E_PROBE_FAILED, E_TRANSCODE_FAILED, E_TRANSCODE_TIMEOUT, E_FFMPEG_MISSING,
    E_STORAGE_UNAVAILABLE, E_PIPELINE_FAILED, E_INTERNAL,
})

USER_MESSAGE = {
    E_NO_VIDEO_STREAM: "That file has no video track we can read. Please upload a match recording.",
    E_CORRUPT_MEDIA: "This recording appears to be incomplete or corrupted. Try re-exporting it and uploading again.",
    E_UNSUPPORTED_CODEC: "We can't decode this video's format. Re-export it as MP4 (H.264) and try again.",
    E_TOO_LONG: "This recording is longer than we can analyze. Trim it to the games you want reviewed.",
    E_TOO_LARGE: "This file is larger than the maximum upload size.",
    E_RESOLUTION_TOO_LARGE: "This video's resolution is beyond what we can process.",
    E_FPS_TOO_HIGH: "This video's frame rate is beyond what we can process.",
    E_ZERO_DURATION: "This recording has no playable duration.",
    E_OBJECT_MISSING: "We couldn't find the uploaded file. Please upload it again.",
    E_SIZE_MISMATCH: "The upload didn't finish completely. Please try uploading again.",
    E_PROBE_FAILED: "We couldn't read this video. Please try again.",
    E_TRANSCODE_FAILED: "We couldn't prepare this video for analysis. Please try again.",
    E_TRANSCODE_TIMEOUT: "Preparing this video took too long. Try a shorter clip.",
    E_FFMPEG_MISSING: "Video processing is temporarily unavailable. Please try again shortly.",
    E_STORAGE_UNAVAILABLE: "Storage is temporarily unavailable. Please try again shortly.",
    E_PIPELINE_FAILED: "We couldn't analyze this match. Please try again.",
    E_INTERNAL: "Something went wrong on our side. Please try again.",
}


class MediaError(Exception):
    def __init__(self, code: str, detail: str = "", stage: Optional[str] = None):
        self.code = code
        self.detail = detail
        self.stage = stage
        super().__init__(f"{code}: {detail}"[:2000])

    @property
    def user_message(self) -> str:
        return USER_MESSAGE.get(self.code, USER_MESSAGE[E_INTERNAL])

    @property
    def retryable(self) -> bool:
        return self.code in RETRYABLE
