---
name: netops-data-migrations
description: Design and review Nexora NetOps PostgreSQL schemas, migrations, indexes, transactions, locking, repositories, and data backfills. Use whenever changing backend/database, persistent models, SQL queries, constraints, or deployment data compatibility.
---

# NetOps Data Migrations

## Workflow

1. Inspect `backend/database/schema.py`, migration tracking in `backend/database/migrations/`, database helpers, and every query touching the table.
2. Make schema changes idempotent and safe for existing installations with real data.
3. Add a numbered migration when deployed databases need transformation; keep fresh-install schema aligned.
4. Use PostgreSQL semantics as authoritative. Retain SQLite only where existing tests intentionally support it.
5. Plan nullable introduction, backfill, constraint enforcement, indexes, rollback/recovery, and concurrent access.

## Conventions

- Parameterize values; never interpolate user input into SQL.
- Use transactions and `FOR UPDATE` for race-sensitive state transitions.
- Add indexes for established query patterns, not speculatively.
- Preserve foreign-key integrity and define deletion behavior deliberately.
- Do not edit or delete user database files during validation.

## Verification

Run migration and schema tests, affected CRUD tests, and a fresh-schema initialization. Test upgrading from the immediately previous schema where practical.
