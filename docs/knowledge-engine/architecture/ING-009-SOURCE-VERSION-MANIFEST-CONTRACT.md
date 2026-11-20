# ING-009 source-version manifest contract

ING-009 closes the provenance write boundary for all ingestion paths. The
existing `kb_source_registry` row remains the canonical Source identity; every
new `kb_source_version` row now also receives a server-owned
`metadata.source_manifest` object with the same immutable facts represented in
typed columns.

The manifest records registry ID, tenant and canonical URL; SHA-256 content
hash, byte size and timezone-aware capture time; final fetch URL, HTTP status,
content type, ETag and Last-Modified; parser name/version; hash-only raw
content reference/storage; verification method and version status. The body is
never copied into metadata, API results or audit details. References that look
like filesystem paths fail closed.

`record_source_version` is still the only persistence writer. It builds and
validates the manifest after content/hash/URL checks, overrides any caller
attempt to replace the server-owned manifest, and keeps the existing tenant
scope, append-only fact guard and `(tenant, source, content_hash)`
deduplication. Existing m0116 columns and V1 source hints are preserved; no
new production DDL is required.

The pure manifest builder has no network or filesystem side effects. Rollback
disables collection writes while retaining immutable version facts and the V1
source-hint read path.
