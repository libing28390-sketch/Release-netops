# CAT-018 Official Catalog / Custom Collection Boundary

CAT-018 freezes a clear ownership boundary for knowledge collections.

The reviewed product catalog is an `official_catalog` projection. It is
server-authoritative, read-only, and non-mutable through the catalog API. The
existing CAT-015 version import/rollback path remains the only reviewed
control-plane path for changing catalog snapshots.

Custom collections use a separate `/api/knowledge-v2/collections` contract.
They are tenant-scoped and may be created, edited, or archived only by the
`knowledge_collection` resource permissions. Their product membership is
represented by opaque `catalog_model_refs`; source vendor, family, series,
model, and software facts are never copied into a writable custom row.

The current implementation is intentionally contract-only and process-local
until the DB-001/DB-013 physical `kb_collection` migration gate is approved.
No production DDL, backfill, or V1 route change is part of CAT-018. All
mutations require bounded fields, optimistic concurrency where applicable,
explicit archive confirmation, tenant isolation, and a redacted audit event.

Rollback is route/adapter removal or disablement; official catalog facts and
V1 metadata remain untouched.
