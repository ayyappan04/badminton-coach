"""Postgres-only integrity constraints.

Guards that SQLite cannot express. They are conditional on the dialect so the
same migration chain runs locally, but the constraints that actually protect
production data are real database constraints there, not conventions.

Revision ID: 0002_pg_constraints
Revises: 0001_baseline
"""
from alembic import op

revision = "0002_pg_constraints"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    # Exactly one current analysis run per video. "Which numbers are the real
    # ones" is not a question that should be settled by whichever concurrent
    # writer committed last.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_analysis_runs_one_current
        ON analysis_runs (video_id)
        WHERE is_current
    """)

    # One live asset of each type per video. A second analysis_proxy row for
    # the same video means one of them is an orphan nobody will ever delete.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_video_assets_live_type
        ON video_assets (video_id, asset_type)
        WHERE deleted_at IS NULL
    """)

    # An object key maps to at most one live asset row, so reconciliation can
    # trust the mapping in both directions.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_video_assets_live_object
        ON video_assets (storage_bucket, storage_path)
        WHERE deleted_at IS NULL
    """)

    # One active upload session per video.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_upload_sessions_active
        ON upload_sessions (video_id)
        WHERE status IN ('created', 'uploading')
    """)

    # Partial indexes for the two hottest operational scans: the worker's
    # stale-lease sweep, and every user-facing video listing (which now always
    # filters out tombstones).
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_analysis_runs_active_lease
        ON analysis_runs (lease_expires_at)
        WHERE status IN ('claimed', 'running')
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_videos_live_owner_created
        ON videos (owner_user_id, created_at DESC)
        WHERE deleted_at IS NULL
    """)

    # Analytics JSONB is queried by block name from the comparison endpoints.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_match_analytics_gin
        ON match_analytics USING gin (analytics jsonb_path_ops)
    """)

    op.execute("""
        ALTER TABLE videos
        ADD CONSTRAINT ck_videos_progress_range
        CHECK (progress_pct >= 0 AND progress_pct <= 100)
    """)


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE videos DROP CONSTRAINT IF EXISTS ck_videos_progress_range")
    for name in (
        "ix_match_analytics_gin", "ix_videos_live_owner_created",
        "ix_analysis_runs_active_lease", "uq_upload_sessions_active",
        "uq_video_assets_live_object", "uq_video_assets_live_type",
        "uq_analysis_runs_one_current",
    ):
        op.execute(f"DROP INDEX IF EXISTS {name}")
