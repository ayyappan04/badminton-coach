"""The worker loop.

Deliberately boring: poll, execute, ack or retry, repeat. All the interesting
behaviour lives in `handlers`, because that is the part that must be correct
under crashes. Concurrency is configurable but defaults to one — computer
vision saturates a core and a frame budget, and two pipelines on one box
mostly slow each other down.
"""
from __future__ import annotations

import logging
import signal
import threading
import time
from typing import Optional

from app.core import config
from app.core.observability import (
    JOBS_DEAD_LETTERED, configure_logging, log, metrics, worker_identity,
)
from app.db.session import SessionLocal
from app.jobs import get_dispatcher
from app.jobs.base import JobMessage
from app.jobs.handlers import JobOutcome, execute, requeue_stalled

logger = logging.getLogger("app.jobs.runner")

#: How often to sweep for leases whose worker disappeared.
STALL_SWEEP_INTERVAL_S = 120


class Worker:
    def __init__(self, concurrency: Optional[int] = None,
                 poll_interval_s: Optional[float] = None):
        self.dispatcher = get_dispatcher()
        self.concurrency = concurrency or config.WORKER_CONCURRENCY
        self.poll_interval = poll_interval_s or config.QUEUE_POLL_INTERVAL_S
        self.worker_id = worker_identity()
        self._stop = threading.Event()
        self._last_sweep = 0.0
        self.processed = 0

    def request_stop(self, *_args) -> None:
        """SIGTERM handler. Finishes the message in hand rather than abandoning
        it — a container being rescheduled should not cost a whole analysis."""
        log(logger, logging.INFO, "shutdown requested; finishing current job")
        self._stop.set()

    def install_signal_handlers(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, self.request_stop)
            except (ValueError, OSError):
                pass  # not the main thread (tests)

    def _sweep(self) -> None:
        now = time.monotonic()
        if now - self._last_sweep < STALL_SWEEP_INTERVAL_S:
            return
        self._last_sweep = now
        try:
            with SessionLocal() as db:
                requeue_stalled(db, self.dispatcher)
            self._sweep_failures = 0
        except Exception:  # noqa: BLE001
            # Full detail the first time, then a one-liner. A recurring
            # infrastructure fault should not bury every other log line.
            self._sweep_failures = getattr(self, "_sweep_failures", 0) + 1
            if self._sweep_failures == 1:
                logger.warning("stall sweep failed", exc_info=True)
            else:
                log(logger, logging.WARNING, "stall sweep still failing",
                    consecutive=self._sweep_failures)

    def handle(self, message: JobMessage) -> str:
        try:
            outcome = execute(message)
        except Exception:  # noqa: BLE001 — a handler must never kill the loop
            logger.exception("handler raised")
            outcome = JobOutcome.RETRY

        if outcome == JobOutcome.ACK:
            self.dispatcher.ack(message)
        elif outcome == JobOutcome.DEAD_LETTER:
            self.dispatcher.dead_letter(message, "handler returned dead_letter")
            metrics.incr(JOBS_DEAD_LETTERED)
        else:
            if message.read_count >= config.JOB_MAX_ATTEMPTS:
                # Redelivered too many times. Park it rather than letting it
                # cycle forever ahead of healthy work.
                self.dispatcher.dead_letter(
                    message, f"exceeded {config.JOB_MAX_ATTEMPTS} deliveries")
                metrics.incr(JOBS_DEAD_LETTERED)
            else:
                # Exponential backoff so a dependency outage is not hammered.
                delay = min(300, 15 * (2 ** message.read_count))
                self.dispatcher.nack(message, delay_s=delay)
        self.processed += 1
        return outcome

    def run_once(self) -> int:
        self._sweep()
        messages = self.dispatcher.receive(
            max_messages=self.concurrency, visibility_timeout_s=config.JOB_LEASE_S)
        for message in messages:
            if self._stop.is_set():
                self.dispatcher.nack(message, delay_s=0)
                break
            self.handle(message)
        try:
            metrics.gauge("queue_depth", self.dispatcher.depth())
        except Exception:  # noqa: BLE001
            pass
        return len(messages)

    def preflight(self) -> list:
        """Check the things that make this worker able to do any work at all.

        A worker whose schema is missing will otherwise loop forever, logging a
        stack trace every sweep — technically resilient, but the first thing an
        operator sees on a fresh deploy is a wall of traceback rather than
        "you did not run the migrations". Say it once, clearly, at boot.
        """
        from sqlalchemy import inspect as sa_inspect
        from app.db.session import engine
        from app.media import ffmpeg

        problems = []
        try:
            tables = set(sa_inspect(engine).get_table_names())
            missing = {"videos", "analysis_runs", "video_assets"} - tables
            if missing:
                problems.append(
                    f"database schema incomplete (missing: {', '.join(sorted(missing))}). "
                    "Run `alembic upgrade head` against DATABASE_URL before starting workers."
                )
        except Exception as exc:  # noqa: BLE001
            problems.append(f"cannot reach the database: {exc}")

        if not ffmpeg.available():
            problems.append(
                "ffmpeg not found. The worker cannot probe or normalize media without it."
            )
        return problems

    def run_forever(self) -> None:
        configure_logging()
        self.install_signal_handlers()

        for problem in self.preflight():
            log(logger, logging.ERROR, "preflight check failed", problem=problem)
        # Deliberately does NOT exit: a database that is briefly unreachable at
        # boot should be retried, not turned into a crash-loop. The loop below
        # backs off, and the messages above tell an operator what to fix.

        if hasattr(self.dispatcher, "ensure_queues"):
            try:
                self.dispatcher.ensure_queues()
            except Exception:  # noqa: BLE001
                logger.warning("could not ensure queues exist", exc_info=True)
        log(logger, logging.INFO, "worker started", worker_id=self.worker_id,
            backend=getattr(self.dispatcher, "backend", "?"),
            concurrency=self.concurrency)
        while not self._stop.is_set():
            try:
                handled = self.run_once()
            except Exception:  # noqa: BLE001
                logger.exception("worker loop error")
                handled = 0
            if handled == 0:
                self._stop.wait(self.poll_interval)
        log(logger, logging.INFO, "worker stopped", processed=self.processed)


def main() -> None:
    Worker().run_forever()


if __name__ == "__main__":
    main()
