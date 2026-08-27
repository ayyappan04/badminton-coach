-- Row Level Security.
--
-- The FastAPI control plane and the Python worker connect with the service
-- role and bypass RLS entirely; they enforce ownership in application code.
-- These policies are the layer BELOW that. If the anon key leaks, or someone
-- reaches PostgREST directly, the database still refuses to hand over another
-- user's match.
--
-- The posture is deliberately asymmetric:
--   * authenticated users may SELECT their own rows
--   * authenticated users may not INSERT, UPDATE or DELETE anything
--
-- Processing state, analysis confidence, pipeline results and ownership are
-- decided by the pipeline, never by a client. The ABSENCE of a write policy is
-- the enforcement: RLS denies by default.
--
-- Requires: backend/alembic migrations already applied (tables must exist).

-- ---------------------------------------------------------------------------
-- Policy helpers
-- ---------------------------------------------------------------------------
-- In `private`, not `public`: PostgREST exposes public, which would publish
-- these SECURITY DEFINER functions as callable /rest/v1/rpc/ endpoints.
CREATE SCHEMA IF NOT EXISTS private;
REVOKE ALL ON SCHEMA private FROM anon, authenticated, public;
GRANT USAGE ON SCHEMA private TO authenticated, service_role;

COMMENT ON SCHEMA private IS
  'RLS policy helpers. Not exposed through PostgREST, so these SECURITY '
  'DEFINER functions cannot be invoked as RPC endpoints.';

-- SECURITY DEFINER so a policy can consult coach_reviews without the caller
-- needing to read it. search_path pinned empty + fully-qualified names, so a
-- temp table cannot shadow a real one.
CREATE OR REPLACE FUNCTION private.owns_video(p_video_id text)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = ''
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.videos v
    WHERE v.id = p_video_id
      AND v.owner_user_id = auth.uid()::text
      AND v.deleted_at IS NULL
  )
$$;

CREATE OR REPLACE FUNCTION private.can_read_video(p_video_id text)
RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER SET search_path = ''
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.videos v
    WHERE v.id = p_video_id
      AND v.deleted_at IS NULL
      AND (
        v.owner_user_id = auth.uid()::text
        OR EXISTS (
          -- The only non-owner read path in the product: a coach holding an
          -- ACTIVE review on this exact video. Revoking the review revokes the
          -- access in the same statement.
          SELECT 1 FROM public.coach_reviews cr
          WHERE cr.video_id = v.id
            AND cr.coach_user_id = auth.uid()::text
            AND cr.status = 'active'
        )
      )
  )
$$;

REVOKE ALL ON FUNCTION private.owns_video(text) FROM public, anon;
REVOKE ALL ON FUNCTION private.can_read_video(text) FROM public, anon;
GRANT EXECUTE ON FUNCTION private.owns_video(text) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION private.can_read_video(text) TO authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Videos and the production lifecycle tables
-- ---------------------------------------------------------------------------
ALTER TABLE public.videos ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.videos FORCE ROW LEVEL SECURITY;

CREATE POLICY videos_select_own ON public.videos
  FOR SELECT TO authenticated
  USING (owner_user_id = auth.uid()::text AND deleted_at IS NULL);

CREATE POLICY videos_select_coach ON public.videos
  FOR SELECT TO authenticated
  USING (
    deleted_at IS NULL
    AND EXISTS (
      SELECT 1 FROM public.coach_reviews cr
      WHERE cr.video_id = videos.id
        AND cr.coach_user_id = auth.uid()::text
        AND cr.status = 'active'
    )
  );

ALTER TABLE public.video_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.video_assets FORCE ROW LEVEL SECURITY;
CREATE POLICY video_assets_select_own ON public.video_assets
  FOR SELECT TO authenticated
  USING (owner_user_id = auth.uid()::text AND deleted_at IS NULL);

ALTER TABLE public.upload_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.upload_sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY upload_sessions_select_own ON public.upload_sessions
  FOR SELECT TO authenticated USING (user_id = auth.uid()::text);

ALTER TABLE public.analysis_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.analysis_runs FORCE ROW LEVEL SECURITY;
CREATE POLICY analysis_runs_select_own ON public.analysis_runs
  FOR SELECT TO authenticated USING (owner_user_id = auth.uid()::text);

ALTER TABLE public.processing_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processing_events FORCE ROW LEVEL SECURITY;
-- Realtime subscribes here for live progress, and RLS applies to Realtime, so
-- this policy is also what stops a subscription leaking another user's stream.
CREATE POLICY processing_events_select_own ON public.processing_events
  FOR SELECT TO authenticated USING (owner_user_id = auth.uid()::text);

ALTER TABLE public.storage_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.storage_usage FORCE ROW LEVEL SECURITY;
CREATE POLICY storage_usage_select_own ON public.storage_usage
  FOR SELECT TO authenticated USING (user_id = auth.uid()::text);

-- ---------------------------------------------------------------------------
-- CV analysis output -- gated on the parent video, which folds coach access in
-- without restating the rule nine times.
-- ---------------------------------------------------------------------------
ALTER TABLE public.calibration ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.calibration FORCE ROW LEVEL SECURITY;
CREATE POLICY calibration_select ON public.calibration
  FOR SELECT TO authenticated USING (private.can_read_video(video_id));

ALTER TABLE public.tracked_persons ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tracked_persons FORCE ROW LEVEL SECURITY;
CREATE POLICY tracked_persons_select ON public.tracked_persons
  FOR SELECT TO authenticated USING (private.can_read_video(video_id));

ALTER TABLE public.pose_frames ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.pose_frames FORCE ROW LEVEL SECURITY;
CREATE POLICY pose_frames_select ON public.pose_frames
  FOR SELECT TO authenticated USING (private.can_read_video(video_id));

ALTER TABLE public.shuttle_frames ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.shuttle_frames FORCE ROW LEVEL SECURITY;
CREATE POLICY shuttle_frames_select ON public.shuttle_frames
  FOR SELECT TO authenticated USING (private.can_read_video(video_id));

ALTER TABLE public.rallies ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rallies FORCE ROW LEVEL SECURITY;
CREATE POLICY rallies_select ON public.rallies
  FOR SELECT TO authenticated USING (private.can_read_video(video_id));

ALTER TABLE public.shots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.shots FORCE ROW LEVEL SECURITY;
CREATE POLICY shots_select ON public.shots
  FOR SELECT TO authenticated USING (private.can_read_video(video_id));

ALTER TABLE public.coaching_insights ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coaching_insights FORCE ROW LEVEL SECURITY;
CREATE POLICY coaching_insights_select ON public.coaching_insights
  FOR SELECT TO authenticated USING (private.can_read_video(video_id));

ALTER TABLE public.match_analytics ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.match_analytics FORCE ROW LEVEL SECURITY;
CREATE POLICY match_analytics_select ON public.match_analytics
  FOR SELECT TO authenticated USING (private.can_read_video(video_id));

ALTER TABLE public.user_corrections ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.user_corrections FORCE ROW LEVEL SECURITY;
CREATE POLICY user_corrections_select_own ON public.user_corrections
  FOR SELECT TO authenticated USING (user_id = auth.uid()::text);

-- ---------------------------------------------------------------------------
-- Identity and profile
-- ---------------------------------------------------------------------------
ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.users FORCE ROW LEVEL SECURITY;
CREATE POLICY users_select_self ON public.users
  FOR SELECT TO authenticated USING (id = auth.uid()::text);

ALTER TABLE public.player_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.player_profiles FORCE ROW LEVEL SECURITY;
CREATE POLICY player_profiles_select_own ON public.player_profiles
  FOR SELECT TO authenticated USING (user_id = auth.uid()::text);

ALTER TABLE public.profile_history_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.profile_history_snapshots FORCE ROW LEVEL SECURITY;
CREATE POLICY profile_history_select_own ON public.profile_history_snapshots
  FOR SELECT TO authenticated USING (user_id = auth.uid()::text);

ALTER TABLE public.consent_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.consent_settings FORCE ROW LEVEL SECURITY;
CREATE POLICY consent_settings_select_own ON public.consent_settings
  FOR SELECT TO authenticated USING (user_id = auth.uid()::text);

-- ---------------------------------------------------------------------------
-- Coach review
-- ---------------------------------------------------------------------------
ALTER TABLE public.coach_reviews ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coach_reviews FORCE ROW LEVEL SECURITY;
CREATE POLICY coach_reviews_select_party ON public.coach_reviews
  FOR SELECT TO authenticated
  USING (student_user_id = auth.uid()::text OR coach_user_id = auth.uid()::text);

ALTER TABLE public.coach_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.coach_notes FORCE ROW LEVEL SECURITY;
CREATE POLICY coach_notes_select_party ON public.coach_notes
  FOR SELECT TO authenticated
  USING (coach_user_id = auth.uid()::text OR private.owns_video(video_id));

-- ---------------------------------------------------------------------------
-- Community
-- ---------------------------------------------------------------------------
ALTER TABLE public.friendships ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.friendships FORCE ROW LEVEL SECURITY;
CREATE POLICY friendships_select_party ON public.friendships
  FOR SELECT TO authenticated
  USING (user_id_a = auth.uid()::text OR user_id_b = auth.uid()::text);

ALTER TABLE public.shared_clips ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.shared_clips FORCE ROW LEVEL SECURITY;
CREATE POLICY shared_clips_select ON public.shared_clips
  FOR SELECT TO authenticated
  USING (
    created_by_user_id = auth.uid()::text
    OR (visibility = 'friends' AND EXISTS (
          SELECT 1 FROM public.friendships f
          WHERE f.status = 'accepted'
            AND ((f.user_id_a = auth.uid()::text AND f.user_id_b = shared_clips.created_by_user_id)
              OR (f.user_id_b = auth.uid()::text AND f.user_id_a = shared_clips.created_by_user_id))
       ))
  );

ALTER TABLE public.practice_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.practice_plans FORCE ROW LEVEL SECURITY;
CREATE POLICY practice_plans_select_own ON public.practice_plans
  FOR SELECT TO authenticated USING (created_by_user_id = auth.uid()::text);

ALTER TABLE public.challenges ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.challenges FORCE ROW LEVEL SECURITY;
CREATE POLICY challenges_select_party ON public.challenges
  FOR SELECT TO authenticated
  USING (created_by_user_id = auth.uid()::text OR opponent_user_id = auth.uid()::text);

ALTER TABLE public.clubs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.clubs FORCE ROW LEVEL SECURITY;
CREATE POLICY clubs_select_member ON public.clubs
  FOR SELECT TO authenticated
  USING (
    owner_user_id = auth.uid()::text
    OR EXISTS (SELECT 1 FROM public.club_memberships m
               WHERE m.club_id = clubs.id AND m.user_id = auth.uid()::text)
  );

ALTER TABLE public.club_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.club_memberships FORCE ROW LEVEL SECURITY;
CREATE POLICY club_memberships_select ON public.club_memberships
  FOR SELECT TO authenticated
  USING (
    user_id = auth.uid()::text
    OR EXISTS (SELECT 1 FROM public.club_memberships m2
               WHERE m2.club_id = club_memberships.club_id
                 AND m2.user_id = auth.uid()::text)
  );

-- ---------------------------------------------------------------------------
-- Shared reference catalogue -- not derived from anybody's footage.
-- ---------------------------------------------------------------------------
ALTER TABLE public.drills ENABLE ROW LEVEL SECURITY;
CREATE POLICY drills_select_all ON public.drills
  FOR SELECT TO authenticated USING (true);

ALTER TABLE public.technique_references ENABLE ROW LEVEL SECURITY;
CREATE POLICY technique_refs_select_all ON public.technique_references
  FOR SELECT TO authenticated USING (true);

-- ---------------------------------------------------------------------------
-- Server-only tables: RLS ON, ZERO policies.
--
-- RLS denies by default, so no client role can read these at all, while the
-- service role bypasses RLS and the API reaches them normally. The Supabase
-- linter reports these as `rls_enabled_no_policy` at INFO level -- that finding
-- is the intended state here, not an oversight.
-- ---------------------------------------------------------------------------
ALTER TABLE public.api_keys         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.api_keys         FORCE  ROW LEVEL SECURITY;
ALTER TABLE public.one_time_tokens  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.one_time_tokens  FORCE  ROW LEVEL SECURITY;
ALTER TABLE public.training_assets  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.training_assets  FORCE  ROW LEVEL SECURITY;
ALTER TABLE public.consent_records  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.consent_records  FORCE  ROW LEVEL SECURITY;
ALTER TABLE public.annotations      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.annotations      FORCE  ROW LEVEL SECURITY;
ALTER TABLE public.processing_jobs  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.processing_jobs  FORCE  ROW LEVEL SECURITY;
ALTER TABLE public.alembic_version  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.alembic_version  FORCE  ROW LEVEL SECURITY;
