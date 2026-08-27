-- Private storage buckets and their policies.
--
-- Three buckets rather than one, because they have different lifecycles:
--   video-originals  immutable sources; strictest access; retention policy
--   video-derived    reproducible proxies/stills/artifacts; cached hard
--   avatars          small, different sharing rules
--
-- All private. A match recording is somebody's footage of themselves in a
-- sports hall. There is no version of "public bucket for convenience" that is
-- acceptable for this content.
--
-- The authorization rule is one line, repeated: the FIRST path segment of an
-- object key must equal auth.uid(). That is why backend/app/storage/paths.py
-- builds every key as {user_id}/{video_id}/... and rejects any segment it did
-- not generate itself -- the naming convention IS the security boundary, so it
-- is enforced in code and again in the database.

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES
  ('video-originals', 'video-originals', false, 5368709120,
   ARRAY['video/mp4','video/quicktime','video/x-msvideo','video/webm',
         'video/x-matroska','application/octet-stream']),
  ('video-derived',  'video-derived',  false, 5368709120,
   ARRAY['video/mp4','image/jpeg','image/png','application/json','application/gzip']),
  ('avatars',        'avatars',        false, 5242880,
   ARRAY['image/jpeg','image/png','image/webp'])
ON CONFLICT (id) DO UPDATE
  SET public             = EXCLUDED.public,
      file_size_limit    = EXCLUDED.file_size_limit,
      allowed_mime_types = EXCLUDED.allowed_mime_types;

-- ---------------------------------------------------------------------------
-- video-originals
-- ---------------------------------------------------------------------------
-- INSERT into your own prefix is the ONLY write grant the system gives a
-- browser, and it is what makes the direct TUS upload safe: tampering with the
-- object path to point at another user's folder is refused by Postgres, not by
-- our API.
CREATE POLICY "originals: insert into own prefix"
  ON storage.objects FOR INSERT TO authenticated
  WITH CHECK (
    bucket_id = 'video-originals'
    AND (storage.foldername(name))[1] = auth.uid()::text
  );

CREATE POLICY "originals: read own"
  ON storage.objects FOR SELECT TO authenticated
  USING (
    bucket_id = 'video-originals'
    AND (storage.foldername(name))[1] = auth.uid()::text
  );

-- Deliberately NO update policy. Originals are immutable: overwriting the
-- source of a completed analysis would silently invalidate every number
-- derived from it, with no way to detect that it had happened. Re-uploading
-- means a new video id and a new key.
CREATE POLICY "originals: delete own"
  ON storage.objects FOR DELETE TO authenticated
  USING (
    bucket_id = 'video-originals'
    AND (storage.foldername(name))[1] = auth.uid()::text
  );

-- ---------------------------------------------------------------------------
-- video-derived
-- ---------------------------------------------------------------------------
-- Read-only for clients. Proxies, stills and analysis artifacts are produced by
-- the worker under the service role; a client able to write here could swap the
-- analyzed footage after the fact and the scores would still say "verified".
CREATE POLICY "derived: read own"
  ON storage.objects FOR SELECT TO authenticated
  USING (
    bucket_id = 'video-derived'
    AND (storage.foldername(name))[1] = auth.uid()::text
  );

-- ---------------------------------------------------------------------------
-- avatars
-- ---------------------------------------------------------------------------
CREATE POLICY "avatars: manage own"
  ON storage.objects FOR ALL TO authenticated
  USING (
    bucket_id = 'avatars'
    AND (storage.foldername(name))[1] = auth.uid()::text
  )
  WITH CHECK (
    bucket_id = 'avatars'
    AND (storage.foldername(name))[1] = auth.uid()::text
  );
