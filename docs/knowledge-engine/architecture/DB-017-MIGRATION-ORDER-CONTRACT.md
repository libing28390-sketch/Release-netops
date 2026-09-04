# DB-017 Migration Order Contract

## Contract summary

The runner discovers migrations, orders them by version, checks
`schema_migrations`, and commits only after an upgrade succeeds. On failure it
calls `conn.rollback()` and halts higher versions. Additive fields such as
`metadata_json`, JSONB, `exclude_from_rag`, and `DEFAULT 0` are introduced in
a compatibility-safe order before any enforcement step.

## Validation and rollback

Nullable/backfill/validate/enforce phases are separate; a `NOT NULL` or
`NOT VALID` transition is never used to hide incomplete data. DB-018 owns
fresh/idempotent synchronization. A rollback keeps V1 history and returns to
the last committed version.

## Final conclusion

The DB-017 nullable, backfill, validate, enforce, NOT NULL, NOT VALID,
DB-018, V1, and rollback evidence are present.

Final Conclusion: PASS
