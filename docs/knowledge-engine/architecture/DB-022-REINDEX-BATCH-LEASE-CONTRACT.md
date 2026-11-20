# DB-022 Reindex Batch Lease Contract

## Contract summary

Reindexing uses keyset pagination and a bounded
`_select_document_batch` query (`ORDER BY d.id LIMIT ...`). `_ReindexLease`
records heartbeat and `retry_wait` state; `_CONTROL_KEY` and checkpointed
progress make retries deterministic. `MAX_BATCH_SIZE` bounds work per lease.
The shared lease table stores its opaque owner in `owner_token` and acquisition/
expiry instants as PostgreSQL `TIMESTAMPTZ`; claims use an expiry-aware atomic
upsert, and DB-022 follow-up migration m0229 preserves existing lease tokens.

## Safety and rollback

Leases are tenant-scoped and idempotent. A worker losing its lease cannot
publish another worker's generation. Rollback keeps the last valid index and
clears only the uncommitted batch state; source documents and V1 evidence
remain available.

## Final conclusion

The DB-022 keyset, scheduler_locks, heartbeat, retry_wait, idempotent, V1,
and rollback markers are documented.

## Scheduler lock storage follow-up

Migration m0229 separates owner tokens from time columns across the shared
`scheduler_locks` table. A PostgreSQL session timezone of `Asia/Shanghai`
controls timestamp display; stored `TIMESTAMPTZ` values remain absolute
instants. Normal task completion releases its owner-fenced lock immediately;
the lease expiry remains crash recovery.

Final Conclusion: PASS
