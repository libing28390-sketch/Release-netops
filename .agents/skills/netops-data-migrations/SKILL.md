---
name: netops-data-migrations
description: Use when changing PostgreSQL schema, migrations, or their rollout, including indexes, transactions, and backfills.
---

# NetOps Data Migrations

## Workflow

1. Inspect `backend/database/schema.py`, migration tracking in `backend/database/migrations/`, database helpers, and every query touching the table.
2. Make schema changes idempotent and safe for existing installations with real data.
3. Add a numbered migration when deployed databases need transformation; keep fresh-install schema aligned.
4. PostgreSQL is the only supported persistence backend for runtime and tests. Use the shared isolated PostgreSQL fixtures; never validate persistence behavior with SQLite.
5. Plan nullable introduction, backfill, constraint enforcement, indexes, rollback/recovery, and concurrent access.

## Conventions

- Parameterize values; never interpolate user input into SQL.
- Use transactions and `FOR UPDATE` for race-sensitive state transitions.
- Add indexes for established query patterns, not speculatively.
- Preserve foreign-key integrity and define deletion behavior deliberately.
- Do not edit or delete user database files during validation.

## Verification

Run migration and schema tests, affected CRUD tests, and a fresh-schema initialization. Test upgrading from the immediately previous schema where practical.
