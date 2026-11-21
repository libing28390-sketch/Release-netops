# 2026-08-09 ING-013 walkthrough

## Scenario

1. Import the reviewed Cisco URL with body `document version one`.
2. Import the same canonical URL with a different body and a different request key.
3. Import the second body again.

## Expected result

- The first import creates one stable `kb_document` and version `1`.
- The changed hash creates version `2` with `supersedes_version_id` pointing to version `1`.
- The repeated second hash replays version `2`; the version count remains two.
- Every row is tenant-scoped and source-version backed; V1 rows remain untouched.

## Evidence

`backend/tests/catalog/test_ing013_document_version.py` covers append, replay, hash mismatch, tenant conflict and verified source-reference fallback. `backend/tests/database/test_m0117_knowledge_v2_document_versions.py` covers migration presence and immutable fact enforcement.

