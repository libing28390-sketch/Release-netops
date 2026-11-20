# CHK-014 Shadow Index walkthrough

CHK-014 adds a PostgreSQL-only retrieval generation control plane.  The legacy
`ai_document`/`ai_document_chunk` projection remains the V1 source.  A build
copies a tenant's eligible chunks into an additive shadow table with FTS,
pg_trgm and pgvector indexes, then verification records bounded counts and
tenant invariants before promotion.

Promotion locks the target and current active row in one transaction.  The
retriever includes the committed `index_version` in its cache key and reads
the shadow table only when the generation is active.  A failed/not-ready
generation cannot be promoted.  Rollback marks the current generation
`rolled_back`, restores `previous_generation_id`, and invalidates only the
affected tenant cache.

The PostgreSQL probe runs migration idempotency, dual-generation build,
tenant isolation, active cutover, not-ready rejection, RAG shadow-read and
rollback checks inside one transaction and rolls it back.  SQLite is not used
as an acceptance backend.

