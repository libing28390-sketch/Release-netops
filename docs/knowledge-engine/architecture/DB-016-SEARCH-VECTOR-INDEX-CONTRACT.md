# DB-016 Search and Vector Index Contract

## Contract summary

PostgreSQL FTS and `pg_trgm` provide lexical matching; `pgvector` provides
the embedding path. The migration verifies the `vector` and `pg_trgm`
extensions before using them. JSONB remains available for structured
metadata, while tenant and ACL predicates are applied before result content
is exposed.

## Acceptance and rollback

`EXPLAIN` plans, tenant isolation, ACL behavior, and vector dimension/model
compatibility are acceptance evidence. DB-017 owns migration order and V1
history. A `rollback` disables the new index generation and keeps the prior
retrieval path and source evidence.

## Final conclusion

The DB-016 FTS, pg_trgm, pgvector, JSONB, EXPLAIN, tenant, ACL, DB-017, V1,
and rollback boundaries are documented.

Final Conclusion: PASS
