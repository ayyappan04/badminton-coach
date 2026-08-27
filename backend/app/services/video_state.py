"""The video lifecycle, as an explicit transition model.

Previously `videos.status` was a free-form string assigned from five different
places. That is fine until two of them race: a worker writing `analyzed` while
a user cancels, or a retried job resetting `failed` back to `processing` after
the row was already deleted. Every transition now goes through `advance()`,
which refuses moves that are not on the graph.

Legacy vocabulary is preserved exactly — `uploaded`, `processing`,
`needs_player_selection`, `analyzed`, `failed` mean what they always meant, so
existing rows and existing API consumers stay valid. The new states describe
stages that previously had no name.
"""
from __future__ import annotations

from typing import Dict, FrozenSet, Optional

CREATED = "created"
UPLOADING = "uploading"
UPLOADED = "uploaded"
VALIDATING = "validating"
QUEUED = "queued"
NORMALIZING = "normalizing"
PROCESSING = "processing"
NEEDS_PLAYER_SELECTION = "needs_player_selection"
ANALYZED = "analyzed"
FAILED = "failed"
CANCELLED = "cancelled"
DELETED = "deleted"

ALL_STATES: FrozenSet[str] = frozenset({
    CREATED, UPLOADING, UPLOADED, VALIDATING, QUEUED, NORMALIZING, PROCESSING,
    NEEDS_PLAYER_SELECTION, ANALYZED, FAILED, CANCELLED, DELETED,
})

#: States from which no further automatic progress happens.
TERMINAL: FrozenSet[str] = frozenset({ANALYZED, FAILED, CANCELLED, DELETED})

#: States where the video occupies a worker or a queue slot.
IN_FLIGHT: FrozenSet[str] = frozenset({VALIDATING, QUEUED, NORMALIZING, PROCESSING})

TRANSITIONS: Dict[str, FrozenSet[str]] = {
    CREATED:      frozenset({UPLOADING, CANCELLED, FAILED, DELETED}),
    UPLOADING:    frozenset({UPLOADED, UPLOADING, CANCELLED, FAILED, DELETED}),
    UPLOADED:     frozenset({VALIDATING, QUEUED, CANCELLED, FAILED, DELETED}),
    VALIDATING:   frozenset({QUEUED, FAILED, CANCELLED, DELETED}),
    QUEUED:       frozenset({NORMALIZING, PROCESSING, QUEUED, FAILED, CANCELLED, DELETED}),
    NORMALIZING:  frozenset({PROCESSING, FAILED, CANCELLED, DELETED, QUEUED}),
    # QUEUED is reachable again from PROCESSING: that is a stale-lease reclaim
    # after a worker died mid-run, not a user-visible move backwards.
    PROCESSING:   frozenset({NEEDS_PLAYER_SELECTION, ANALYZED, FAILED, CANCELLED,
                             DELETED, QUEUED}),
    NEEDS_PLAYER_SELECTION: frozenset({ANALYZED, PROCESSING, QUEUED, FAILED,
                                       CANCELLED, DELETED}),
    # Reprocessing an already-analyzed video is an explicit user action and
    # creates a NEW analysis run; the old one is retained.
    ANALYZED:     frozenset({QUEUED, PROCESSING, DELETED, ANALYZED,
                             NEEDS_PLAYER_SELECTION}),
    FAILED:       frozenset({QUEUED, DELETED, CANCELLED}),
    CANCELLED:    frozenset({DELETED}),
    DELETED:      frozenset(),
}

#: What the UI groups each state under. Uploading and processing are
#: deliberately distinct: a user watching "Uploading 100%" while the server
#: transcodes has been told something false.
GROUP: Dict[str, str] = {
    CREATED: "upload", UPLOADING: "upload", UPLOADED: "upload",
    VALIDATING: "process", QUEUED: "process", NORMALIZING: "process",
    PROCESSING: "process",
    NEEDS_PLAYER_SELECTION: "action_required",
    ANALYZED: "ready",
    FAILED: "error", CANCELLED: "error", DELETED: "gone",
}

LABEL: Dict[str, str] = {
    CREATED: "Preparing upload",
    UPLOADING: "Uploading",
    UPLOADED: "Upload complete",
    VALIDATING: "Checking the recording",
    QUEUED: "Queued for analysis",
    NORMALIZING: "Optimizing video",
    PROCESSING: "Analyzing",
    NEEDS_PLAYER_SELECTION: "Confirm which player is you",
    ANALYZED: "Analyzed",
    FAILED: "Failed",
    CANCELLED: "Cancelled",
    DELETED: "Deleted",
}


class InvalidTransition(ValueError):
    def __init__(self, current: str, target: str):
        super().__init__(f"illegal video state transition: {current} -> {target}")
        self.current = current
        self.target = target


def can(current: Optional[str], target: str) -> bool:
    if target not in ALL_STATES:
        return False
    if not current:
        return target in (CREATED, UPLOADING, UPLOADED)
    return target in TRANSITIONS.get(current, frozenset())


def advance(video, target: str, *, stage: Optional[str] = None,
            progress_pct: Optional[int] = None, strict: bool = True) -> bool:
    """Move a Video row to `target`, refusing illegal moves.

    Returns True when the state changed. With `strict=False` an illegal move
    is ignored rather than raised — used by the worker, where losing a race
    against a user's delete should not crash the job.
    """
    current = video.status
    if current == target and stage is None and progress_pct is None:
        return False
    if not can(current, target):
        if strict:
            raise InvalidTransition(current, target)
        return False
    video.status = target
    if stage is not None:
        video.stage = stage
    if progress_pct is not None:
        video.progress_pct = max(0, min(100, int(progress_pct)))
    if target in TERMINAL and target != FAILED:
        video.processing_error = None
    return True
