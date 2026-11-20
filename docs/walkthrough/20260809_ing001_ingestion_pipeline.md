# ING-001 walkthrough

## State and phase flow

```text
queued -> running -> retry_wait -> running
   |         |  \-> paused -> running
   |         \----> cancel_requested -> cancelled
   \-------------------------------> cancel_requested

accepted -> scoped -> fetched -> parsed -> normalized -> classified
          -> chunked -> embedded -> indexed -> validated -> committed -> completed
```

`succeeded` is reachable only after `completed` and full server-derived
progress. Non-retryable errors end in `failed`; retryable errors consume a
bounded retry budget. Lease expiry records `WORKER_LOST` and fences the stale
worker before recovery.

## Demonstrated safety cases

- Duplicate tenant/idempotency requests replay the same job only when the
  scope fingerprint matches.
- Phase jumps without explicit evidence, counter corruption, unknown fields,
  stale lease heartbeats, and invalid terminal transitions are rejected.
- Cancellation is safe-point based and repeated requests are idempotent.
- Error payloads carry stable codes and safe messages, never raw content.

See [ING-001 Evidence](../knowledge-engine-v2/evidence/ING-001.md) and the
frozen [ING-001 contract](../knowledge-engine-v2/architecture/ING-001-INGESTION-PIPELINE-CONTRACT.yaml).
