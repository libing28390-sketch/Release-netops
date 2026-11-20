# CAT-015 Product Catalog Version Import, Diff, and Rollback

CAT-015 defines the complete version bundle and the safe lifecycle around it. A bundle must explicitly contain a bounded version label, the full model set, and the full Alias set. The service canonicalizes identity and software-scope fields, rejects secrets/control characters/cross-tenant rows, and rejects ambiguous Alias groups from becoming active.

Preview is always dry-run and returns added/removed/changed model and Alias rows with a truncation flag. Import and rollback require explicit confirmation plus an optimistic `expected_active_version_id`. Every successful operation records a redacted audit event. History is retained and rollback changes only the active pointer.

Because DB-006 is still contract-only, CAT-015 uses an explicit process-local registry (`contract_only_ephemeral_version_registry`) rather than applying production DDL. The API and validation semantics are persistence-neutral and can be moved behind the approved PostgreSQL repository at the migration/release gate. V1 metadata and legacy resolver paths are not rewritten.
