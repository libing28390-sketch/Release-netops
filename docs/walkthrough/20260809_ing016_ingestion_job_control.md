# ING-016 Ingestion Job Control Walkthrough

## Scope

The source checklist requirement is `ING-016 P0/BE/M`: implement task
progress, cancellation, retry, failed phases, and error details.

## Operator flow

1. An existing importer creates a tenant-scoped `IngestionJob` and returns the
   server-derived progress snapshot.
2. `GET /api/knowledge-v2/ingestion/jobs` lists snapshots for the authenticated
   tenant; counters cannot be written through the API.
3. `POST .../jobs/{id}/cancel` records an idempotent cancellation request. A
   queued job without a lease is acknowledged immediately; a running worker
   remains `cancel_requested` until its safe-point acknowledgement.
4. A non-retryable or exhausted error sets the current phase to `failed` and
   stores an allowlisted structured error. `GET .../jobs/{id}/errors` exposes
   only that safe view.
5. `POST .../jobs/{id}/retry` leaves the failed parent intact and creates one
   new queued child attempt with `retry_of_job_id`; repeated requests reuse an
   active child.

## Safety boundary

The control surface uses the dedicated `knowledge_import` permissions and a
server-owned tenant predicate. Error classification removes raw exception text,
credentials, document bodies, and device output. The implementation is
process-local until the DB-011 durable job migration and the next ING-017 lease
gate; V1 reindex tables are not changed.
