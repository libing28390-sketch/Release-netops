# ING-015 Document Lifecycle Contract

ING-015 makes the V2 lifecycle explicit through `lifecycle_status`. The
compatibility `status` column remains available to existing adapters: a
Published V2 record projects to `active`, a Superseded version projects to
`archived`, and the other states retain their matching safe projection. V1
`ai_document` and `ai_document_chunk` rows are never rewritten.

Only Published records are retrieval eligible. Publishing, quarantine,
disabling and superseding all run inside one tenant-scoped compare-and-set
transaction. A Superseded version must name a newer Published replacement in
the same Document. Each request has a tenant-unique request ID, an immutable
event record and a bounded audit payload; repeating a request returns its
recorded result without a second transition.
