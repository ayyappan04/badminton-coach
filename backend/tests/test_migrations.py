"""Migration mechanics.

Production must never depend on `Base.metadata.create_all()` running at import
time. These tests check that the Alembic chain is coherent, applies cleanly to
an empty database, reverses, and actually matches the models it was generated
from.
"""
import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
VERSIONS = BACKEND / "alembic" / "versions"


def alembic(*args, db_url: str):
    """Run alembic in a subprocess so it gets a clean config and its own
    engine, exactly as a deploy would."""
    import os
    env = {**os.environ, "DATABASE_URL": db_url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND, env=env, capture_output=True, text=True,
    )


@pytest.fixture()
def fresh_db(tmp_path):
    return f"sqlite:///{tmp_path / 'migrate.db'}"


def test_migration_chain_is_linear_and_complete():
    revisions, downs = {}, {}
    for path in VERSIONS.glob("*.py"):
        text = path.read_text()
        rev = next((l.split("=")[1].strip().strip("'\"")
                    for l in text.splitlines() if l.startswith("revision =")), None)
        down = next((l.split("=")[1].strip().strip("'\"")
                     for l in text.splitlines() if l.startswith("down_revision =")), None)
        assert rev, f"{path.name} declares no revision"
        revisions[rev] = path.name
        downs[rev] = None if down in ("None", None) else down

    roots = [r for r, d in downs.items() if d is None]
    assert len(roots) == 1, f"expected exactly one root revision, found {roots}"
    for rev, down in downs.items():
        if down is not None:
            assert down in revisions, f"{rev} points at missing parent {down}"


def test_upgrade_head_creates_the_full_schema(fresh_db, tmp_path):
    result = alembic("upgrade", "head", db_url=fresh_db)
    assert result.returncode == 0, result.stderr

    import sqlite3
    con = sqlite3.connect(str(tmp_path / "migrate.db"))
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    # The tables the production architecture depends on.
    for required in ("videos", "video_assets", "upload_sessions", "analysis_runs",
                     "processing_events", "storage_usage", "users", "alembic_version"):
        assert required in tables, f"missing table: {required}"

    version = con.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    assert version, "alembic_version was not stamped"


def test_downgrade_and_upgrade_round_trip(fresh_db):
    assert alembic("upgrade", "head", db_url=fresh_db).returncode == 0
    down = alembic("downgrade", "base", db_url=fresh_db)
    assert down.returncode == 0, down.stderr
    up = alembic("upgrade", "head", db_url=fresh_db).returncode
    assert up == 0


def test_models_match_the_migrations(fresh_db):
    """A model change without a migration is a schema drift that only shows up
    on the deploy that breaks production."""
    assert alembic("upgrade", "head", db_url=fresh_db).returncode == 0
    result = alembic("check", db_url=fresh_db)
    if result.returncode != 0 and "No new upgrade operations" not in result.stdout:
        pytest.fail(
            "models have diverged from migrations; run "
            "`alembic revision --autogenerate`:\n"
            f"{result.stdout}\n{result.stderr}"
        )


def test_offline_sql_generation_works(fresh_db):
    """`alembic upgrade head --sql` is how the hosted Supabase project's DDL is
    produced, so it must stay working and must not need a live connection."""
    result = alembic("upgrade", "head", "--sql",
                     db_url="postgresql+psycopg://u:p@127.0.0.1:5432/x")
    assert result.returncode == 0, result.stderr
    sql = result.stdout
    assert "CREATE TABLE videos" in sql
    assert "CREATE TABLE video_assets" in sql
    assert "JSONB" in sql, "Postgres dialect did not render the JSONB variants"
    assert "uq_analysis_runs_one_current" in sql, "partial unique index missing"


def test_production_does_not_create_tables_at_import_time():
    """`create_all()` as a production migration mechanism means any process
    start can silently mutate the schema."""
    main = (BACKEND / "app" / "main.py").read_text()
    assert "if not config.IS_PRODUCTION:" in main
    create_line = next(i for i, l in enumerate(main.splitlines())
                       if "Base.metadata.create_all" in l)
    guard_line = next(i for i, l in enumerate(main.splitlines())
                      if "if not config.IS_PRODUCTION:" in l)
    assert guard_line < create_line, "create_all() is not guarded"


def test_alembic_config_holds_no_connection_string():
    ini = (BACKEND / "alembic.ini").read_text()
    for line in ini.splitlines():
        stripped = line.strip()
        if stripped.startswith("sqlalchemy.url") and "=" in stripped:
            value = stripped.split("=", 1)[1].strip()
            assert not value, f"alembic.ini pins a connection string: {value}"


# --- connection-string handling ------------------------------------------

def test_database_url_normalisation():
    """Every managed Postgres hands out `postgresql://`, which SQLAlchemy maps
    to psycopg2 — a driver this project does not ship. The first production
    deploy died on exactly that."""
    from app.db.session import normalize_database_url as norm

    # What Supabase actually gives you.
    assert norm("postgresql://postgres:pw@db.abc.supabase.co:5432/postgres") == \
        "postgresql+psycopg://postgres:pw@db.abc.supabase.co:5432/postgres"

    # The legacy alias SQLAlchemy rejects outright.
    assert norm("postgres://user:pw@host:5432/db") == \
        "postgresql+psycopg://user:pw@host:5432/db"

    # An explicit driver is always respected.
    for explicit in ("postgresql+psycopg://u:p@h/d",
                     "postgresql+asyncpg://u:p@h/d",
                     "postgresql+psycopg2://u:p@h/d"):
        assert norm(explicit) == explicit

    # Non-Postgres URLs pass through untouched.
    assert norm("sqlite:///./app.db") == "sqlite:///./app.db"
    assert norm("") == ""


def test_password_special_characters_survive_normalisation():
    """Supabase passwords routinely contain punctuation. Rewriting the scheme
    must not disturb the rest of the URL."""
    from app.db.session import normalize_database_url as norm

    raw = "postgresql://postgres.abc:p%40ss-w0rd%2F%3F@aws-0.pooler.supabase.com:6543/postgres"
    out = norm(raw)
    assert out.startswith("postgresql+psycopg://")
    assert out.endswith("p%40ss-w0rd%2F%3F@aws-0.pooler.supabase.com:6543/postgres")


def test_pooler_username_is_qualified_with_the_project_ref():
    """Supabase's pooler is multi-tenant and identifies the project from the
    USERNAME. Copying the direct connection string and changing only host and
    port yields `FATAL: password authentication failed for user "postgres"` —
    an error that blames the one part that was right."""
    from app.db.session import qualify_pooler_username as q

    SB = "https://calgdgaaogsxfdnodlmn.supabase.co"
    pooler = "aws-0-us-west-2.pooler.supabase.com:6543/postgres"

    assert q(f"postgresql://postgres:pw@{pooler}", SB) == \
        f"postgresql://postgres.calgdgaaogsxfdnodlmn:pw@{pooler}"

    # Already qualified: untouched.
    already = f"postgresql://postgres.calgdgaaogsxfdnodlmn:pw@{pooler}"
    assert q(already, SB) == already

    # A direct connection does not use tenant-qualified usernames.
    direct = "postgresql://postgres:pw@db.calgdgaaogsxfdnodlmn.supabase.co:5432/postgres"
    assert q(direct, SB) == direct

    # A deliberately different user is never rewritten.
    custom = f"postgresql://myuser:pw@{pooler}"
    assert q(custom, SB) == custom

    # Without SUPABASE_URL the ref is unknown, so nothing is invented.
    assert q(f"postgresql://postgres:pw@{pooler}", "") == f"postgresql://postgres:pw@{pooler}"


def test_pooler_qualification_preserves_password_punctuation():
    from app.db.session import qualify_pooler_username as q

    SB = "https://abc.supabase.co"
    url = "postgresql://postgres:p%40ss:word%2F@aws-0-eu-west-1.pooler.supabase.com:6543/postgres"
    out = q(url, SB)
    assert out.startswith("postgresql://postgres.abc:")
    assert out.endswith("@aws-0-eu-west-1.pooler.supabase.com:6543/postgres")
    # Everything after the first colon is the password, untouched.
    assert ":p%40ss:word%2F@" in out
