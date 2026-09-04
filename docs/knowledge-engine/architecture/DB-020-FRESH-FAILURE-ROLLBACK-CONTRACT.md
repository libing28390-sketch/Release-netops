# DB-020 Fresh Failure Rollback Contract

## Contract summary

The matrix covers `fresh`, `repeat`, `partial`, and controlled `failure`
scenarios. Each migration is transactional in PostgreSQL; only committed
versions enter `schema_migrations`, and a corrected retry can continue from
the last valid V1 history.

## Safety and rollback

Tests use disposable PostgreSQL databases and never delete production
history. The rollback assertion covers data, DDL, tracking rows, and the
absence of leaked partial objects. SQLite is mentioned only as a historical
compatibility note; the CI contract and production path are PostgreSQL.

## Final conclusion

The DB-020 fresh/repeat/partial/failure/rollback, schema_migrations, V1,
PostgreSQL, and Final Conclusion markers are documented.

Final Conclusion: PASS
