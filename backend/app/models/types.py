"""Column types that adapt to the dialect.

SQLite gets plain JSON (dev, tests); Postgres gets JSONB, which is what makes
the GIN indexes in the analytics migrations possible. Declaring this once
avoids the usual drift where half the models are queryable in production and
half are not.
"""
from sqlalchemy import JSON, Text
from sqlalchemy.dialects.postgresql import JSONB

JSONType = JSON().with_variant(JSONB(astext_type=Text()), "postgresql")
