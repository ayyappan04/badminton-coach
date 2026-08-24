"""Safe handling of user-supplied video uploads.

Threat model addressed here:
* Disk exhaustion — enforce a hard byte cap *while streaming*, not after.
* Content/extension mismatch — validate container magic bytes, so renaming
  `payload.elf` to `clip.mp4` does not get it stored as a video.
* Path traversal — the stored name is server-generated; the client filename is
  never used to build a path.
* Header/HTML injection via the display filename — sanitise before storing.
* Undecodable input — reject early with a clear message instead of failing
  deep inside the CV pipeline.
"""
import re
import unicodedata
import uuid
from pathlib import Path
from typing import Optional, Tuple

from fastapi import HTTPException, UploadFile, status

from app.core.config import (
    MAX_UPLOAD_BYTES, MAX_ORIGINAL_FILENAME_LEN, UPLOADS_DIR,
)

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v", ".avi", ".webm"}

# Container signatures. ISO-BMFF (mp4/mov/m4v) puts 'ftyp' at offset 4.
_ISO_BMFF_BRAND_OFFSET = 4
_CHUNK = 1024 * 1024


def sanitize_display_filename(raw: Optional[str]) -> str:
    """Produce a safe, human-readable label for the original filename.

    This value is only ever displayed or used in Content-Disposition — never
    to construct a filesystem path. We strip directory components, control
    characters (CR/LF would allow response-header injection), and angle
    brackets/quotes that could confuse a downstream renderer.
    """
    if not raw:
        return "upload"
    name = unicodedata.normalize("NFKC", raw)
    name = name.replace("\\", "/").split("/")[-1]          # drop any path parts
    name = "".join(ch for ch in name if ch.isprintable())   # drop CR/LF/NUL etc.
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "", name)          # header/HTML-unsafe
    name = name.strip(" .") or "upload"
    if len(name) > MAX_ORIGINAL_FILENAME_LEN:
        stem, dot, ext = name.rpartition(".")
        ext = f".{ext}" if dot else ""
        name = stem[: MAX_ORIGINAL_FILENAME_LEN - len(ext)] + ext
    return name


def validated_extension(raw_filename: Optional[str]) -> str:
    """Extension taken from the client name, checked against the allowlist.

    Only the allowlisted literal is ever reused, so `..%2f` style payloads in
    the extension cannot reach the filesystem.
    """
    suffix = Path(sanitize_display_filename(raw_filename)).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file type '{suffix or 'unknown'}'. "
                f"Supported formats: {', '.join(sorted(ALLOWED_EXTENSIONS))}."
            ),
        )
    return suffix


def looks_like_supported_video(head: bytes) -> bool:
    """Magic-byte check for the containers we accept."""
    if len(head) < 12:
        return False
    if head[_ISO_BMFF_BRAND_OFFSET:_ISO_BMFF_BRAND_OFFSET + 4] == b"ftyp":
        return True                                   # mp4 / mov / m4v
    if head[:4] == b"RIFF" and head[8:12] == b"AVI ":
        return True                                   # avi
    if head[:4] == b"\x1a\x45\xdf\xa3":
        return True                                   # webm / mkv
    return False


def save_upload(file: UploadFile) -> Tuple[Path, str, int]:
    """Stream an upload to disk with a hard size cap and signature checks.

    Returns (stored_path, sanitized_display_name, size_bytes).
    Any rejection removes the partial file before raising.
    """
    display_name = sanitize_display_filename(file.filename)
    ext = validated_extension(file.filename)

    dest_path = (UPLOADS_DIR / f"{uuid.uuid4().hex}{ext}").resolve()
    # Belt and braces: the generated name cannot escape, but assert it anyway.
    if dest_path.parent != Path(UPLOADS_DIR).resolve():
        raise HTTPException(status_code=400, detail="Invalid upload destination.")

    total = 0
    head = b""
    try:
        with dest_path.open("wb") as out:
            while True:
                chunk = file.file.read(_CHUNK)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Video exceeds the {MAX_UPLOAD_BYTES // (1024 * 1024)} MB limit.",
                    )
                if len(head) < 32:
                    head += chunk[: 32 - len(head)]
                out.write(chunk)

        if total == 0:
            raise HTTPException(status_code=400, detail="The uploaded file is empty.")
        if not looks_like_supported_video(head):
            raise HTTPException(
                status_code=400,
                detail="That file does not look like a supported video. Please upload an MP4, MOV, AVI, or WebM recording.",
            )
    except HTTPException:
        dest_path.unlink(missing_ok=True)
        raise
    except Exception:
        dest_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="Upload failed. Please try again.")

    return dest_path, display_name, total
