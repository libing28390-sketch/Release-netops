# DB-018 Idempotent Fresh Sync Contract

## Contract summary

`MigrationPlan` is read-only before execution. A `fresh` database receives
ordered `upgrade` calls, a repeat run is `idempotent`, and strict history
rejects unknown versions or name drift. `schema_migrations` is written only
after a successful migration transaction commits.

## Failure and rollback

An exception rolls back the current migration and leaves the previous V1
history available for retry. DB-019 covers the highest-version upgrade and
DB-020 covers fresh failure/rollback matrices. The runner never mutates a
production database as a test fixture.

## Final conclusion

The DB-018 MigrationPlan, fresh, upgrade, strict, idempotent, rollback,
schema_migrations, DB-019, DB-020, V1, and PostgreSQL boundaries are
documented.

Final Conclusion: PASS
