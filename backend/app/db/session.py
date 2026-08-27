from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.core.config import DATABASE_URL


class Base(DeclarativeBase):
    pass


def normalize_database_url(url: str) -> str:
    """Make the connection string SQLAlchemy needs out of the one you were given.

    Supabase, Heroku, Railway and Neon all hand out `postgresql://...` (or
    `postgres://...`). SQLAlchemy maps a bare `postgresql://` to psycopg2,
    which this project does not ship — it uses psycopg 3 — so the process dies
    at import with `ModuleNotFoundError: No module named 'psycopg2'`.

    Expecting every operator to hand-edit the scheme into `postgresql+psycopg://`
    is a footgun: the value is copied from a dashboard, the edit is invisible in
    review, and the failure appears only on deploy. Normalising here costs
    nothing and removes the whole class of mistake.

    An explicit driver is always respected, so `postgresql+asyncpg://` or a
    deliberate `+psycopg2` still does what it says.
    """
    if not url:
        return url
    # `postgres://` is the legacy alias; SQLAlchemy rejects it outright.
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


RESOLVED_DATABASE_URL = normalize_database_url(DATABASE_URL)

connect_args = (
    {"check_same_thread": False} if RESOLVED_DATABASE_URL.startswith("sqlite") else {}
)

engine_kwargs = {"connect_args": connect_args}
if not RESOLVED_DATABASE_URL.startswith("sqlite"):
    # Supabase's transaction pooler closes idle connections, and a pooled
    # connection that died server-side surfaces as a confusing mid-request
    # error. pre_ping costs one round trip and turns that into a transparent
    # reconnect.
    engine_kwargs["pool_pre_ping"] = True
    engine_kwargs["pool_recycle"] = 1800

engine = create_engine(RESOLVED_DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
