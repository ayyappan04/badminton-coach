# API Design

Base URL: `/api/v1`. Auth via JWT bearer token (`Authorization: Bearer <token>`), issued by `/auth/login`.

## Auth
```
POST   /auth/register            {email, password, display_name}
POST   /auth/login               {email, password} -> {token, user}
GET    /auth/me                  -> current user
```

## Videos & analysis
```
POST   /videos                          multipart upload {file, match_format?, recorded_at?}
                                         -> {video_id, status: "uploaded"}
GET    /videos                          -> list of user's videos (library view)
GET    /videos/{id}                     -> video detail + status
DELETE /videos/{id}                     -> deletes original + derived assets

POST   /videos/{id}/process             kick off analysis job (idempotent)
GET    /videos/{id}/status              -> {status, progress_pct, stage}

GET    /videos/{id}/tracked-persons     -> candidate tracked people (for "which one is me")
POST   /videos/{id}/tracked-persons/{tp_id}/claim   {role: "self"}  -- user confirms identity

GET    /videos/{id}/calibration         -> court calibration result + confidence
PATCH  /videos/{id}/calibration         {court_corners_px: [...]}  -- manual correction

GET    /videos/{id}/rallies             -> rally list with timestamps
GET    /videos/{id}/shots               -> shot list (filterable by rally, player, type)
GET    /videos/{id}/insights            -> coaching insights, timestamp-linked
GET    /videos/{id}/overlay-manifest    -> per-frame overlay data (skeleton, court, shuttle, trails)
                                            for canvas rendering synced to <video>
GET    /videos/{id}/heatmap             -> court occupancy heatmap data (per tracked person)
GET    /videos/{id}/scorecards          -> technique / footwork / positioning / stability scores
```

## Technique reference ("Correct Form" simulator)
```
GET    /technique-references                    -> list (shot/movement names)
GET    /technique-references/{shot_or_movement}  -> full phase breakdown, mistakes, variations
GET    /drills                                   -> drill library
GET    /drills?tag=split_step_timing             -> filtered
```

## Player profile
```
GET    /profile                    -> longitudinal profile: strengths, weaknesses, play-style, radar scores
GET    /profile/history            -> radar score snapshots over time (trend chart data)
GET    /profile/training-plan      -> current recommended weekly plan
```

## Consent & privacy
```
GET    /consent-settings
PATCH  /consent-settings           {allow_training_data_contribution, default_clip_share_scope, ...}
POST   /videos/{id}/export         -> request a data export (original + derived)
DELETE /account                    -> full account + data deletion (with confirmation flow)
```

## Community
```
GET    /friends                          -> friend list + pending requests
POST   /friends/requests                 {to_user_id}
POST   /friends/requests/{id}/accept
GET    /users/{id}/public-profile         -> respects that user's sharing scope

GET    /clips/shared                      -> clips shared with me
POST   /videos/{id}/clips                 {start_s, end_s, visibility, caption}

POST   /practice-plans                    {participants, scheduled_at, location, drill_ids}
GET    /practice-plans
POST   /challenges                        {opponent_user_id, description}
GET    /clubs / POST /clubs / POST /clubs/{id}/members
```

## Conventions

- All list endpoints paginated (`?page=&page_size=`).
- Every analysis object that involves estimation includes a `confidence: float (0-1)` field and, where relevant, a `limitations: string[]` field (e.g. `["low_frame_rate", "camera_occlusion_net_area"]`).
- Long-running work (`POST /videos/{id}/process`) returns immediately with a job reference; clients poll `GET /videos/{id}/status` or open a WebSocket at `/ws/videos/{id}` for push updates.
- Errors follow `{error: {code, message, user_message}}` — `user_message` is always coaching-appropriate plain language (e.g. "This video's resolution is too low for reliable shuttle tracking" rather than a stack trace).
