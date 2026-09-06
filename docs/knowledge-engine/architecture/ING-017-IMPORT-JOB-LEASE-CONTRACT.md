# ING-017 Import Job Lease Contract

ING-017 adds the worker-facing lease adapter. It reuses the existing
PostgreSQL-authoritative `scheduler_locks` table already approved by DB-022,
with a tenant-hashed `knowledge_import:<tenant-hash>:<job-id>` lock name. A
unique-key collision returns `LEASE_HELD`; only the matching opaque owner token
can heartbeat or release the row. The adapter then claims the ING-001
state-machine fence, so database and process-local races must both pass.

Public job snapshots do not expose worker owner tokens or fencing secrets. A
running lease cannot be released early; terminal completion, failure, or
cancellation must be recorded first. Expiry is recoverable as `WORKER_LOST`
and follows the existing bounded retry policy. No new production DDL is
introduced, and V1 reindex/generic job rows remain untouched while DB-011/MIG
continues to gate the future durable `kb_import_job` table.
