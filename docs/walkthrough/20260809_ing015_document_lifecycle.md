# 2026-08-09 ING-015 walkthrough

## Scenario

1. Import a reviewed URL. The V2 Document and Version start as `draft`.
2. Publish the version. It becomes retrieval eligible and the compatibility
   status becomes `active`.
3. Quarantine it for review, then disable it. Neither state is retrieval
   eligible.
4. Import and publish a newer version, then mark the old version
   `superseded` with the new version ID.
5. Repeat the publish request and attempt a stale, cross-tenant or Viewer
   transition.

## Expected result

- Every transition is tenant-scoped, CAS-protected and audit recorded.
- A repeated request is idempotent; a stale revision returns a stable conflict.
- A Superseded version is history-only while its Published replacement keeps
  the Document eligible.
- Viewer/cross-tenant requests fail closed, and event/audit output contains no
  body, URL payload, credentials or unrestricted exception text.

## Evidence

`backend/tests/catalog/test_ing015_document_lifecycle.py` covers the state
machine, idempotency, supersession, CAS, permission, tenant and API contract
boundaries. `backend/tests/database/test_m0119_knowledge_v2_document_lifecycle.py`
covers the additive schema, event table and idempotent migration.
