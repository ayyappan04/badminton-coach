# Data Privacy, Consent, and Training-Data Rights

## Core rule

**A user's uploaded match video is never used to train or improve any model unless that user explicitly opts in per-video (or via a standing setting they can revoke at any time).** This is enforced structurally, not just by policy:

- `videos` (user recordings) and `training_assets` (model-training corpus) are separate tables with separate storage prefixes/buckets and separate access-control policies.
- The only path from one to the other is through a `consent_records` row with `subject_type = user_video_contribution`, created at the moment of opt-in, carrying a snapshot of the consent text the user agreed to (so later ToS changes don't retroactively reinterpret old consent).
- Revoking consent (`consent_settings.allow_training_data_contribution = false`, or deleting the specific contribution) removes the asset from future training runs; already-trained model weights are not retroactively altered, but this limitation is disclosed to the user in the consent UI.

## Non-user (licensed/public) training footage

For footage sourced from BWF channels, broadcasters, or other public sources:

1. Nothing is downloaded or used by default. The system assumes public visibility ≠ usage rights.
2. Every `training_assets` row requires: `source` (licensed_broadcast / open_license / internally_collected / user_opt_in), `license_type`, `license_terms_url`, `usage_restrictions`, and `rights_holder`.
3. `review_status` starts at `pending` — an asset cannot be used in an annotation/training job until a human reviewer sets it to `approved` after checking the license terms actually permit the intended use (including, specifically, ML training — many broadcast licenses permit viewing but not derivative-model training).
4. If licensing status is ever unclear, the default is exclusion, not inclusion.

## Human-in-the-loop annotation workflow

- Annotators work only against `approved` `training_assets`.
- Annotation payloads (player/court/racket/shuttle/shot labels) are stored in `annotations` with `status: draft → reviewed → rejected/approved`, tied to `annotator_user_id` and a `reviewed_by` reviewer — no auto-accepted annotations feed training.

## User-facing consent controls

Exposed via `/consent-settings` and surfaced in onboarding + account settings:

- **Training contribution** (default OFF): "Allow anonymized clips and pose data from my matches to help improve the coaching models." Off by default; per-video override available.
- **Retention policy**: keep indefinitely / auto-delete originals after 90 days / after 1 year (derived insights can be retained separately at reduced granularity if the user wants trend history without keeping raw video).
- **Sharing scope** (community features): private / friends / public, settable per-video, per-clip, and as an account default. Applies independently to (a) full analysis data, (b) individual shared clips, (c) match results, (d) basic profile info — a user can share results with friends while keeping full technique analysis private.
- **Deletion**: account deletion cascades to videos, derived CV data, and any of the user's own clips; a confirmation step explains exactly what is deleted vs. retained (e.g., previously licensed training assets from other sources are obviously unaffected, but any of *their own* opted-in contributions are also removed).
- **Export**: a user can request a bundle of their original videos + derived data (JSON) at any time.

## Anonymization for training contributions

When a user opts in to contribute footage, before it enters `training_assets` the pipeline:
- Strips embedded metadata (GPS/device identifiers) from the video file.
- Optionally blurs spectator faces in the background (bystanders never consented; the contributing player did).
- Stores only pose/court/shot-label data plus short clips needed for annotation review, not the full original file, unless full-resolution is specifically required and separately confirmed.
