# DB-019 Current Highest Upgrade Test Contract

## Contract summary

The V2 upgrade fixture starts from the `114` snapshot and applies the `115`
upgrade against a cloned PostgreSQL database. It verifies that `V1` tables
and prior tracking rows remain unchanged, that the upgrade is idempot, and
that a fresh install and upgrade produce the same committed
`schema_migrations` history.

## Failure and rollback

Migration exceptions roll back data and DDL in PostgreSQL. Unknown versions,
name drift, raw document capture, fake vector extensions, and production
database mutation are forbidden. DB-020 owns the fresh partial-failure matrix
and the `MIG` evidence boundary. A rollback returns to the last committed
version without deleting source evidence.

## Final conclusion

The DB-019 115/114 V2, fresh, upgrade, idempot, rollback,
schema_migrations, DB-020, MIG, V1, and PostgreSQL evidence is present.

Final Conclusion: PASS
