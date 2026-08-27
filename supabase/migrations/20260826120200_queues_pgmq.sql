-- Supabase Queues (pgmq).
--
-- Chosen over an external broker for one specific reason: enqueueing a job and
-- writing the analysis_run row can share a single Postgres transaction. That
-- removes the "run created but job never queued" failure mode outright, which
-- is otherwise exactly what an outbox pattern exists to paper over. The brief
-- asks for a conscious choice between the two; this is it, and the simpler
-- option is available only because the queue lives in the same database.
--
-- Two queues. The main one carries work. The dead-letter queue keeps messages
-- that exhausted their retries, because silently dropping a poisoned job also
-- destroys the evidence needed to work out why it was poisoned.

CREATE EXTENSION IF NOT EXISTS pgmq;

SELECT pgmq.create('shuttlesense_analysis');
SELECT pgmq.create('shuttlesense_analysis_dlq');

-- The worker connects as the service role and uses pgmq directly. No client
-- role is granted anything: a browser must never be able to enqueue analysis
-- work, nor read another user's job payloads out of the queue table.
REVOKE ALL ON SCHEMA pgmq FROM anon, authenticated;
