# Database Schema

Implemented as SQLAlchemy models in `backend/app/models/`. Shown here in simplified DDL-ish form. All tables have `id` (UUID), `created_at`, `updated_at` unless noted.

## Identity & accounts

```
users
  id, email, hashed_password, display_name, avatar_url,
  created_at, last_active_at

consent_settings (1:1 with users)
  user_id (FK),
  allow_training_data_contribution: bool = false   -- explicit opt-in required
  default_clip_share_scope: enum(private, friends, public) = private
  default_profile_share_scope: enum(private, friends, public) = friends
  retention_policy: enum(keep_indefinitely, delete_after_1y, delete_after_90d)
  updated_at
```

## Video & match data (user-owned, never used for training unless opted in)

```
videos
  id, owner_user_id (FK), storage_path, original_filename,
  duration_seconds, fps, resolution_w, resolution_h,
  match_format: enum(singles, doubles, unknown),
  recorded_at, uploaded_at,
  status: enum(uploaded, processing, needs_player_selection, analyzed, failed),
  camera_view_hint: enum(tripod_baseline, tripod_side, elevated, spectator, unknown),
  processing_error: text nullable

calibration
  id, video_id (FK),
  method: enum(auto_hough, user_assisted, manual),
  homography_matrix: json,          -- pixel -> court-meter mapping
  court_corners_px: json,
  confidence: float,                -- 0-1
  notes: text                       -- e.g. "net line partially occluded"

tracked_persons
  id, video_id (FK), track_id: int, -- raw tracker id before identity resolution
  role: enum(unassigned, self, partner, opponent1, opponent2),
  bounding_boxes: json,             -- [{frame, x, y, w, h, conf}]
  first_frame, last_frame

pose_frames
  id, tracked_person_id (FK), frame_index, timestamp_s,
  landmarks: json,                  -- 33 MediaPipe landmarks {x,y,z,visibility}
  stance_label: enum(neutral, attacking, defensive, lunge, jump, split_step, recovery, unknown),
  balance_score: float nullable, confidence: float

shuttle_frames
  id, video_id (FK), frame_index, timestamp_s,
  position_px: json {x,y}, position_court: json {x,y} nullable,
  estimated_speed_mps: float nullable, confidence: float

rallies
  id, video_id (FK), rally_index, start_frame, end_frame,
  start_timestamp_s, end_timestamp_s, shot_count, confidence

shots
  id, rally_id (FK), tracked_person_id (FK),
  shot_index_in_rally, frame_index, timestamp_s,
  shot_type: enum(serve, clear, drop, smash, drive, lift, net_shot, net_kill, push, block, defensive_return, lob, unknown),
  side: enum(forehand, backhand, unknown),
  contact_height: enum(overhead, underhand, unknown),
  intent: enum(offensive, neutral, defensive, unknown),
  outcome: enum(in, out, net, intercepted, unknown),
  confidence: float

coaching_insights
  id, video_id (FK), tracked_person_id (FK), related_shot_id nullable,
  timestamp_s, category: enum(technique, footwork, positioning, tactics, stamina),
  observed_action: text, likely_impact: text, correction: text,
  drill_id (FK nullable), confidence: float, limitations: text
```

## Coaching content (system-owned reference data, not user-specific)

```
drills
  id, name, category, description, target_issue_tags: json, difficulty

technique_references          -- "Correct Form" simulator content
  id, shot_or_movement_name, singles_or_doubles_context,
  phases: json,   -- [{phase_name, description, keyframe_svg_or_asset}]
  common_beginner_mistakes: json, advanced_variations: json
```

## Longitudinal player profile

```
player_profiles (1:1 with users)
  user_id (FK), matches_analyzed_count, last_updated_at,
  play_style_labels: json,        -- [{label, evidence_summary, confidence}]
  strengths: json, weaknesses: json,
  radar_scores: json              -- {attack, control, endurance, defense, mobility, net_play, power, consistency, tactical_awareness} each 0-100 with confidence

profile_history_snapshots
  id, user_id (FK), video_id (FK), snapshot_at, radar_scores: json, notes: text
```

## Training data governance (physically/logically separate from user videos)

```
training_assets
  id, source: enum(licensed_broadcast, open_license, internally_collected, user_opt_in),
  source_url_or_reference, license_type, license_terms_url,
  usage_restrictions: text, consent_record_id nullable, rights_holder,
  storage_path, added_by_user_id, added_at, review_status: enum(pending, approved, rejected)

consent_records
  id, subject_type: enum(training_asset, user_video_contribution),
  subject_id, consenting_party, consent_text_snapshot, granted_at, revoked_at nullable

annotations
  id, training_asset_id (FK), annotator_user_id, annotation_type,
  payload: json, reviewed_by, reviewed_at, status: enum(draft, reviewed, rejected)
```

## Community

```
friendships
  id, user_id_a, user_id_b, status: enum(pending, accepted, blocked), created_at

shared_clips
  id, video_id (FK), created_by_user_id, clip_start_s, clip_end_s,
  visibility: enum(private, friends, public), caption

clubs / teams
  id, name, owner_user_id, description

club_memberships
  club_id, user_id, role: enum(member, coach, admin)

practice_plans / match_plans
  id, created_by_user_id, participants: json, scheduled_at, location, notes, linked_drill_ids: json

challenges
  id, created_by_user_id, opponent_user_id, description, status, result nullable
```

## Key invariants

- `videos.owner_user_id` rows are **never** joined into `training_assets` unless a `consent_records` row exists for `subject_type = user_video_contribution` referencing that video, and `consent_settings.allow_training_data_contribution` was true at the time.
- Deleting a `users` row (or a user requesting deletion) cascades to `videos`, derived tables, and storage objects, but never deletes `training_assets` rows that were separately licensed (those live under their own rights record, not the user's account).
