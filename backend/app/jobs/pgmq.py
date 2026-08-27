"""Supabase Queues (pgmq) dispatcher.

pgmq gives visibility timeouts, redelivery and an archive table inside the
same Postgres that already holds the domain state. That is worth more here
than a separate broker would be: enqueueing a job and writing the analysis_run
row can share one transaction, which removes the whole class of "job queued
but the database never heard about it" bugs without needing an outbox.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from sqlalchemy import text

from app.core import config
from app.db.session import SessionLocal
from app.jobs.base import JobMessage

logger = logging.getLogger("app.jobs.pgmq")


class PgmqJobDispatcher:
    backend = "pgmq"
    durable = True

    def __init__(self, queue_name: Optional[str] = None):
        self.queue = queue_name or config.QUEUE_ANALYSIS
        self.dlq = f"{self.queue}_dlq"

    # -- helpers -----------------------------------------------------------

    def _session(self):
        return SessionLocal()

    def ensure_queues(self) -> None:
        """Create the queues if they are missing. Safe on every worker boot.

        `pgmq.create()` is NOT idempotent: on an existing queue it tries to
        re-register the queue's sequence with the extension and fails with

            sequence pgmq.q_<name>_msg_id_seq is already a member of
            extension "pgmq"

        Since the queues are normally created by supabase/migrations, that is
        the ordinary case, and every worker boot printed a stack trace for a
        situation that is entirely correct. Ask what exists first, and create
        only what does not.
        """
        with self._session() as db:
            try:
                existing = {
                    row[0] for row in db.execute(text("SELECT queue_name FROM pgmq.list_queues()"))
                }
            except Exception:  # noqa: BLE001 — older pgmq builds lack list_queues()
                existing = set()

            for name in (self.queue, self.dlq):
                if name in existing:
                    logger.debug("queue %s already exists", name)
                    continue
                try:
                    db.execute(text("SELECT pgmq.create(:q)"), {"q": name})
                    logger.info("created queue %s", name)
                except Exception as exc:  # noqa: BLE001
                    # Lost a race with another worker booting at the same time,
                    # or list_queues() was unavailable above. Both are benign.
                    if "already" in str(exc).lower():
                        logger.debug("queue %s already exists (concurrent create)", name)
                        db.rollback()
                        continue
                    raise
            db.commit()

    # -- interface ---------------------------------------------------------

    def enqueue(self, message: JobMessage, delay_s: int = 0, db=None) -> str:
        """Send a message. Pass an existing `db` session to enqueue inside the
        caller's transaction — that is the whole point of using a Postgres
        queue, and it is what makes the outbox pattern unnecessary here."""
        payload = json.dumps(message.to_dict())
        sql = text("SELECT pgmq.send(:q, CAST(:m AS jsonb), :d) AS msg_id")
        params = {"q": self.queue, "m": payload, "d": int(delay_s)}
        if db is not None:
            msg_id = db.execute(sql, params).scalar_one()
            return str(msg_id)
        with self._session() as own:
            msg_id = own.execute(sql, params).scalar_one()
            own.commit()
            return str(msg_id)

    def receive(self, max_messages: int = 1, visibility_timeout_s: int = 900) -> list[JobMessage]:
        """Read with a visibility timeout. If this worker dies before acking,
        the message reappears after `visibility_timeout_s` and another worker
        picks it up."""
        with self._session() as db:
            rows = db.execute(
                text("SELECT msg_id, read_ct, message FROM pgmq.read(:q, :vt, :qty)"),
                {"q": self.queue, "vt": int(visibility_timeout_s), "qty": int(max_messages)},
            ).mappings().all()
            db.commit()
        out: list[JobMessage] = []
        for row in rows:
            raw = row["message"]
            if isinstance(raw, str):
                raw = json.loads(raw)
            out.append(JobMessage.from_dict(raw or {}, receipt=str(row["msg_id"]),
                                            read_count=int(row["read_ct"] or 0)))
        return out

    def ack(self, message: JobMessage) -> bool:
        if not message.receipt:
            return False
        with self._session() as db:
            ok = db.execute(text("SELECT pgmq.delete(:q, CAST(:id AS bigint))"),
                            {"q": self.queue, "id": message.receipt}).scalar()
            db.commit()
        return bool(ok)

    def nack(self, message: JobMessage, delay_s: int = 30) -> bool:
        """Make the message visible again after a delay, so a transient failure
        backs off instead of spinning."""
        if not message.receipt:
            return False
        with self._session() as db:
            db.execute(text("SELECT pgmq.set_vt(:q, CAST(:id AS bigint), :d)"),
                       {"q": self.queue, "id": message.receipt, "d": int(delay_s)})
            db.commit()
        return True

    def dead_letter(self, message: JobMessage, reason: str) -> bool:
        """Move a poisoned message out of the main queue and keep it. Silently
        dropping it would erase the evidence needed to work out why."""
        if not message.receipt:
            return False
        payload = json.dumps({**message.to_dict(), "dead_letter_reason": reason[:500]})
        with self._session() as db:
            db.execute(text("SELECT pgmq.send(:q, CAST(:m AS jsonb))"),
                       {"q": self.dlq, "m": payload})
            db.execute(text("SELECT pgmq.archive(:q, CAST(:id AS bigint))"),
                       {"q": self.queue, "id": message.receipt})
            db.commit()
        logger.error("dead-lettered %s: %s", message.idempotency_key, reason)
        return True

    def depth(self) -> int:
        with self._session() as db:
            row = db.execute(
                text("SELECT queue_length FROM pgmq.metrics(:q)"), {"q": self.queue}
            ).scalar()
        return int(row or 0)

    def health(self) -> bool:
        try:
            with self._session() as db:
                db.execute(text("SELECT 1 FROM pgmq.metrics(:q)"), {"q": self.queue}).first()
            return True
        except Exception:
            logger.warning("pgmq health check failed", exc_info=True)
            return False
