"""Alembic environment.

Reads DATABASE_URL from the environment so no connection string is ever
committed. Supports offline mode (`alembic upgrade head --sql`), which is how
the SQL applied to the hosted Supabase project is generated — one authority
for the schema, rendered rather than hand-written twice.
"""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import Base  # noqa: E402
import app.models  # noqa: E402,F401  registers every table on Base.metadata
from app.core import tokens as _tokens  # noqa: E402,F401  registers one_time_tokens

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    """DATABASE_URL, normalised the same way the application normalises it.

    Without this, `alembic upgrade head` fails with `No module named
    'psycopg2'` on the exact connection string the dashboard hands you, while
    the app itself works — a maddening inconsistency.
    """
    from app.db.session import normalize_database_url

    url = normalize_database_url(os.environ.get("DATABASE_URL", ""))
    if not url:
        raise SystemExit(
            "DATABASE_URL is not set. Point it at the target database, e.g.\n"
            "  export DATABASE_URL=postgresql+psycopg://postgres:PASSWORD@db.<ref>.supabase.co:5432/postgres"
        )
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(), target_metadata=target_metadata, literal_binds=True,
        dialect_opts={"paramstyle": "named"}, compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata,
            compare_type=True,
            # SQLite cannot ALTER most things in place; batch mode rewrites the
            # table instead, so local development can run the same migrations.
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
