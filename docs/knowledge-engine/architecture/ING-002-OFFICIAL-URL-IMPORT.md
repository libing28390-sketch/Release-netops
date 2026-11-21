# ING-002 Single Official URL Import

ING-002 is the first concrete worker on the ING-001 control plane. A request
contains exactly one canonical official HTTPS URL plus reviewed vendor,
product-family, version-scope, and terms evidence. The request is rejected
before any network call if the URL is outside the CAT-001 host/path allowlist,
contains query/fragment/userinfo, or lacks the required review metadata.

The service creates or reuses the tenant's source-registry row, validates and
activates it, then calls the CAT-004 `safe_fetch` boundary. The source registry
records an immutable SHA-256 version manifest, HTTP metadata, parser pin, and
redirect/DNS evidence. Response bytes stay in memory for hashing and are never
returned by the endpoint or stored as raw content by this adapter.

The ING-001 job intentionally stops at `fetched` with
`continuation_required=true`. Parsing, normalization, chunking, embedding,
indexing, quarantine, and Published lifecycle transitions belong to later ING
tasks; this boundary never claims a Published Document prematurely. Repeating
the same tenant/idempotency/scope returns the existing manifest without a
second fetch. No V1 source hint or reindex row is rewritten, and no production
DDL is part of ING-002.
