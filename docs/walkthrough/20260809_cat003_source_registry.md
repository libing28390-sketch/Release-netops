# 2026-08-09 CAT-003 Source Registry walkthrough

## Scope

CAT-003 implements the Source Registry CRUD/lifecycle/validation/version
recording boundary from the frozen DB-008, CAT-001 and CAT-002 contracts.

## Runtime flow

1. `POST /api/knowledge-v2/sources` canonicalizes an HTTPS URL, maps the
   CAT-002 source kind to a DB-008 source type, fills a safe collection policy,
   and creates a `draft` row scoped to the authenticated tenant.
2. `POST /api/knowledge-v2/sources/{id}/validate` runs URL, host, policy,
   secret, official catalog, version-scope and terms checks. It persists the
   redacted validation result and never performs network I/O.
3. `POST /api/knowledge-v2/sources/{id}/enable` repeats validation in the
   write transaction. Only a validated draft/disabled row becomes `active`
   with `fetch_enabled=1`.
4. `POST /api/knowledge-v2/sources/{id}/versions` records a pinned parser,
   SHA-256 content fact and byte size. Duplicate content hashes are idempotent;
   immutable fact fields are guarded by a database trigger.
5. `POST .../disable` and `DELETE ...` are audited soft lifecycle changes;
   physical deletion is not part of CAT-003.

## Verification

The focused CAT-003/m0116 suite passed 6 tests, including cross-tenant denial,
official allowlist failure, policy revalidation, duplicate version idempotence,
fact immutability and route contract coverage. Migration, CAT/DB compatibility,
compile, security scan, frontend lint and production build gates also passed.

