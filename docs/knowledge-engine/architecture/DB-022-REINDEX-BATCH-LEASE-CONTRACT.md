# DB-022 Reindex Batch Lease Contract

## Contract summary

Reindexing uses keyset pagination and a bounded
`_select_document_batch` query (`ORDER BY d.id LIMIT ...`). `_ReindexLease`
records heartbeat and `retry_wait` state; `_CONTROL_KEY` and checkpointed
progress make retries deterministic. `MAX_BATCH_SIZE` bounds work per lease.

## Safety and rollback

Leases are tenant-scoped and idempotent. A worker losing its lease cannot
publish another worker's generation. Rollback keeps the last valid index and
clears only the uncommitted batch state; source documents and V1 evidence
remain available.

## Final conclusion

The DB-022 keyset, scheduler_locks, heartbeat, retry_wait, idempotent, V1,
and rollback markers are documented.

Final Conclusion: PASS
