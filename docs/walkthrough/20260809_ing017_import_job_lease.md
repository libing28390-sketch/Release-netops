# ING-017 Import Job Lease Walkthrough

1. A worker calls `IngestionJobLeaseCoordinator.claim` with a tenant, job and
   worker id. The coordinator first inserts an expiring row in
   `scheduler_locks`, then claims the process-local ING-001 fence.
2. A second worker receives `LEASE_HELD` before it can mutate job state.
3. The owner heartbeats the database row using the opaque owner token and then
   heartbeats the state-machine fencing token. If either comparison fails, the
   worker is stale and cannot continue.
4. After a terminal state, release deletes only the matching owner row. Expired
   rows are eligible for the next claim; the old token cannot release or
   heartbeat the replacement lease.

The lock name hashes tenant identity, public snapshots omit lease owner and
fencing token, and V1 reindex rows are not touched. The adapter is additive and
release-gated without a new migration.
