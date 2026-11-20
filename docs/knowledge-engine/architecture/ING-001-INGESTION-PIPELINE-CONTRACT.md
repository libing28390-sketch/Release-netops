# ING-001 Unified Ingestion Pipeline

ING-001 establishes the control-plane contract used by every future Knowledge
V2 ingestion worker. URL collection, local files, enterprise SOP files,
parsers, chunking, embedding, and indexing share one execution state machine
and one ordered phase machine. A worker cannot invent a local status or emit a
different error shape.

Execution state (`queued`, `running`, `retry_wait`, `paused`,
`cancel_requested`, `cancelled`, `succeeded`, `failed`) is deliberately
separate from the lifecycle status used by the database contract. Phases move
forward from `accepted` through `completed`; a jump requires explicit evidence,
and work phases require a claimed running lease. Terminal success requires the
completed phase and full server-derived progress.

The service enforces tenant-scoped idempotency, bounded retries, cooperative
cancellation, lease heartbeats, fencing tokens, and expired-worker recovery.
Progress counters are validated on the server and clients cannot set a fake
percentage. Errors are mapped to a stable allowlist with retryable versus
non-retryable disposition. Only safe messages and identifiers are returned;
raw documents, device output, prompts, credentials, DSNs, and tokens never
enter the error contract.

The implementation is intentionally process-local until the DB-011 physical
`kb_import_job` migration gate. This is an adapter boundary, not a claim that
production persistence or workers are already enabled. Existing V1 reindex and
generic network-operation jobs remain untouched and are the rollback target.
