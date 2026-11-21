# ING-009 walkthrough

1. CAT-004, ING-002, ING-004 and ING-005 all call the source registry version
   writer with their captured bytes or verified hash reference.
2. The writer computes/validates SHA-256 and byte size, canonicalizes the final
   source URL, validates the timezone-aware capture timestamp and bounds HTTP
   metadata and parser identity.
3. A server-owned `source_manifest` is embedded in the immutable version
   metadata. It contains no body and rejects filesystem references.
4. Duplicate content remains deduplicated by tenant/source/hash; immutable
   source-version fact guards remain active. Tenant authorization and audit
   events are unchanged and continue to carry only metadata.
5. The existing m0116 schema already contains the typed source/hash/HTTP/time/
   parser columns, so this task requires no production migration.

Focused verification is in
`backend/tests/catalog/test_ing009_source_version_manifest.py`.
