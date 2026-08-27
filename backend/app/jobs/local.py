"""In-process dispatcher for development and tests.

Preserves the MVP's behaviour — submit and it runs on a thread — but goes
through the same JobMessage contract as production, so the handler code under
test is the handler code that ships. It is explicitly NOT durable, and
`health()` says so.
"""
from __future__ import annotations

import logging
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from app.core import config
from app.jobs.base import JobMessage

logger = logging.getLogger("app.jobs.local")


class LocalJobDispatcher:
    backend = "local"
    durable = False

    def __init__(self, max_workers: Optional[int] = None, eager: Optional[bool] = None):
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers or max(1, config.WORKER_CONCURRENCY),
            thread_name_prefix="bc-job",
        )
        self._queue: "queue.Queue[JobMessage]" = queue.Queue()
        self._lock = threading.Lock()
        self._counter = 0
        # eager=True runs work immediately on submit, which is what makes a bare
        # `uvicorn` a working dev environment. eager=False buffers instead, so a
        # `runner` loop pulls the message and exercises the same claim/lease
        # path production uses.
        self.eager = config.JOB_EAGER_LOCAL if eager is None else eager

    def _next_receipt(self) -> str:
        with self._lock:
            self._counter += 1
            return f"local-{self._counter}"

    def enqueue(self, message: JobMessage, delay_s: int = 0) -> str:
        receipt = self._next_receipt()
        message.receipt = receipt
        if self.eager:
            from app.jobs.handlers import execute
            def _run(msg: JobMessage = message):
                try:
                    execute(msg)
                except Exception:
                    logger.exception("local job failed: %s", msg.idempotency_key)
            if delay_s > 0:
                threading.Timer(delay_s, _run).start()
            else:
                self._executor.submit(_run)
        else:
            self._queue.put(message)
        return receipt

    def receive(self, max_messages: int = 1, visibility_timeout_s: int = 900) -> list[JobMessage]:
        out: list[JobMessage] = []
        for _ in range(max_messages):
            try:
                out.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return out

    def ack(self, message: JobMessage) -> bool:
        return True

    def nack(self, message: JobMessage, delay_s: int = 30) -> bool:
        message.read_count += 1
        self._queue.put(message)
        return True

    def dead_letter(self, message: JobMessage, reason: str) -> bool:
        logger.error("dead-letter %s: %s", message.idempotency_key, reason)
        return True

    def depth(self) -> int:
        return self._queue.qsize()

    def health(self) -> bool:
        return True
