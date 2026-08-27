-- Realtime for processing progress.
--
-- The frontend subscribes to its own `videos` rows and `processing_events`.
-- RLS applies to Realtime, so a subscription can only ever deliver rows the
-- user could already SELECT -- the live channel is not a way around the
-- policies in 20260826120000_rls_policies.sql.
--
-- Polling remains in the client as a fallback. Correctness must not depend on
-- a websocket staying up: Postgres is the source of truth and Realtime is an
-- optimisation over asking it repeatedly.

ALTER PUBLICATION supabase_realtime ADD TABLE public.videos;
ALTER PUBLICATION supabase_realtime ADD TABLE public.processing_events;

-- REPLICA IDENTITY FULL so an UPDATE payload carries the old row as well as
-- the new one; without it a subscriber cannot tell which column changed.
ALTER TABLE public.videos REPLICA IDENTITY FULL;
