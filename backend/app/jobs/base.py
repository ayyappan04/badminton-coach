"""Job dispatch contract.

The queue distributes work. The database remains the source of truth for
anything a user can see. That split matters: a lost queue message costs a
retry, whereas a queue that owns user-visible state means a message loss is
data loss.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Protocol

#: Operations a worker knows how to perform.
OP_INGEST = "ingest"        # probe -> validate -> normalize -> derived assets
OP_ANALYZE = "analyze"      # the ShuttleSense CV pipeline
OP_CLEANUP = "cleanup"      # delete objects for a tombstoned video

ALL_OPERATIONS = frozenset({OP_INGEST, OP_ANALYZE, OP_CLEANUP})


@dataclass
class JobMessage:
    operation: str
    video_id: str
    analysis_run_id: Optional[str] = None
    pipeline_version: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)

    # Transport bookkeeping, set by the dispatcher on receive.
    receipt: Optional[str] = None
    read_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation": self.operation, "video_id": self.video_id,
            "analysis_run_id": self.analysis_run_id,
            "pipeline_version": self.pipeline_version, "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, raw: Dict[str, Any], receipt: Optional[str] = None,
                  read_count: int = 0) -> "JobMessage":
        return cls(
            operation=raw.get("operation", ""), video_id=raw.get("video_id", ""),
            analysis_run_id=raw.get("analysis_run_id"),
            pipeline_version=raw.get("pipeline_version"),
            payload=raw.get("payload") or {}, receipt=receipt, read_count=read_count,
        )

    @property
    def idempotency_key(self) -> str:
        """video + run + operation + pipeline version, exactly as specified.

        Two deliveries of the same work produce the same key, so the second one
        finds the run already terminal and drops the message instead of
        starting a second pipeline over the same footage.
        """
        return ":".join([
            self.video_id, self.analysis_run_id or "-", self.operation,
            self.pipeline_version or "-",
        ])


class JobDispatcher(Protocol):
    def enqueue(self, message: JobMessage, delay_s: int = 0) -> str: ...

    def receive(self, max_messages: int = 1, visibility_timeout_s: int = 900) -> list[JobMessage]: ...

    def ack(self, message: JobMessage) -> bool:
        """Permanently remove a completed message."""
        ...

    def nack(self, message: JobMessage, delay_s: int = 30) -> bool:
        """Return a message for redelivery after `delay_s`."""
        ...

    def dead_letter(self, message: JobMessage, reason: str) -> bool: ...

    def depth(self) -> int: ...

    def health(self) -> bool: ...
