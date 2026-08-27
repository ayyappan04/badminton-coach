# Supabase-owned migrations

## Ownership boundary

Two migration systems, one authority each. They never define the same object.

| Owner | Owns | Location |
|---|---|---|
| **Alembic** | Application/domain tables, columns, indexes, check constraints | `backend/alembic/versions/` |
| **Supabase SQL** | RLS enablement + policies, storage buckets + storage policies, pgmq queues, database functions, Realtime publication | `supabase/migrations/` |

The rule that keeps them from fighting: Alembic never writes a `POLICY`, a
`storage.bucket`, or a `pgmq` call; Supabase migrations never write a
`CREATE TABLE` for a domain table. Where a Supabase migration references a
table, that table must already exist — so **Alembic runs first**.

## Apply order

```bash
# 1. domain schema (Alembic is the authority)
cd backend
export DATABASE_URL='postgresql+psycopg://postgres:PASSWORD@db.<ref>.supabase.co:5432/postgres'
python -m alembic upgrade head

# 2. platform configuration
cd ..
supabase link --project-ref <ref>
supabase db push
```

To review before applying, render Alembic's SQL without connecting:

```bash
python -m alembic upgrade head --sql > schema.sql
```

## Local development

```bash
supabase start          # local Postgres + Auth + Storage on :54321
supabase db reset       # replays supabase/migrations from scratch
```

`supabase start` does not run Alembic. Run step 1 against the local database
URL that `supabase status` prints, then `supabase db push`.
