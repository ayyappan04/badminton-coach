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


#: Placeholder text that dashboards and templates leave in connection strings.
#: Pasting one of these authenticates with the literal text, which reads as a
#: wrong password — and on Supabase's pooler, repeated attempts trip a circuit
#: breaker whose error then blames authentication rather than the placeholder.
_PLACEHOLDER_MARKERS = (
    "[your-password]", "[password]", "<your-password>", "<password>",
    "your-password", "yourpassword", "your_password", "[db-password]",
    "changeme", "replace-me", "xxxxx",
)


def placeholder_in_url(url: str) -> str:
    """The placeholder left in a connection string, or "" if there is none.

    Only the password segment is examined, so a database legitimately named
    `changeme` is not flagged.
    """
    if not url or "://" not in url or "@" not in url:
        return ""
    _, _, rest = url.partition("://")
    credentials, _, _ = rest.rpartition("@")
    _, sep, password = credentials.partition(":")
    if not sep:
        return ""
    lowered = password.lower()
    for marker in _PLACEHOLDER_MARKERS:
        if marker in lowered:
            return marker
    return ""


def qualify_pooler_username(url: str, supabase_url: str = "") -> str:
    """Add the project ref to the username when connecting through the pooler.

    Supabase's connection poolers are multi-tenant, so they identify the
    project from the USERNAME: `postgres.<project_ref>`, not `postgres`. Copy
    the direct connection string, change the host and port to the pooler, and
    you get:

        FATAL: password authentication failed for user "postgres"

    which points at the password — the one part that was correct. A bare
    `postgres` can never authenticate against the pooler, and the ref is
    already known from SUPABASE_URL, so this is derivable rather than
    guesswork. Logged, not silent.
    """
    if not url or "pooler.supabase.com" not in url or "://" not in url:
        return url

    scheme, _, rest = url.partition("://")
    if "@" not in rest:
        return url
    credentials, _, host_part = rest.rpartition("@")
    user, sep, password = credentials.partition(":")

    # Already qualified, or not the default user — leave it alone.
    if "." in user or user != "postgres":
        return url

    ref = ""
    if supabase_url:
        host = supabase_url.split("://")[-1].split("/")[0]
        if host.endswith(".supabase.co"):
            ref = host[: -len(".supabase.co")]
    if not ref:
        return url

    import sys
    print(
        f"[db] pooler connection with username 'postgres'; qualifying it as "
        f"'postgres.{ref}' from SUPABASE_URL. Supabase's pooler identifies the "
        "project from the username and rejects a bare 'postgres'.",
        file=sys.stderr,
    )
    return f"{scheme}://postgres.{ref}{sep}{password}@{host_part}"


from app.core.config import SUPABASE_URL as _SUPABASE_URL  # noqa: E402

RESOLVED_DATABASE_URL = qualify_pooler_username(
    normalize_database_url(DATABASE_URL), _SUPABASE_URL
)

DATABASE_URL_PLACEHOLDER = placeholder_in_url(RESOLVED_DATABASE_URL)
if DATABASE_URL_PLACEHOLDER:
    import sys as _sys
    print(
        f"[db] DATABASE_URL still contains the placeholder "
        f"'{DATABASE_URL_PLACEHOLDER}' where the password belongs. Every "
        "connection will fail as an authentication error, and Supabase's "
        "pooler will eventually block new connections entirely. Substitute the "
        "real database password.",
        file=_sys.stderr,
    )

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
    # Without a connect timeout a blocked pooler ties up the caller until the
    # OS gives up, which on a readiness probe means the probe itself times out
    # and says nothing useful.
    engine_kwargs["connect_args"] = {**connect_args, "connect_timeout": 10}

engine = create_engine(RESOLVED_DATABASE_URL, **engine_kwargs)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
