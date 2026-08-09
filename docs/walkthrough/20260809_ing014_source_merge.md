# 2026-08-09 ING-014 walkthrough

## Scenario

1. Import the reviewed Cisco 17.9 URL with a body.
2. Import a different reviewed Cisco 17.18 URL with the exact same body.
3. Import a different URL with changed bytes.
4. Attempt to pass a forged URL or content hash into the version adapter.

## Expected result

- The first URL creates one document and one immutable version.
- The equal body reuses that version, returns `merge_same_content_different_source`,
  and appends a second `kb_document_source` observation.
- Changed bytes create a separate document/version when the canonical URL is
  different; incompatible trust/parser/kind also prevents merging.
- Forged source facts fail with `DOCUMENT_SOURCE_FACT_MISMATCH` before any write.
- Tenant predicates prevent cross-tenant content reuse, and V1 rows remain
  unchanged.

## Evidence

`backend/tests/catalog/test_ing014_source_merge.py` covers compatible merge,
changed-content separation, cross-tenant isolation and authoritative-fact
rejection. `backend/tests/database/test_m0118_knowledge_v2_document_sources.py`
covers migration presence, indexes and idempotent upgrade behavior.
