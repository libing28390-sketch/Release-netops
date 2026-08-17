# ING-024 adversarial input verification

ING-024 adds bounded, deterministic QA coverage for hostile document and
source inputs.  The focused suite is kept outside `backend/tests` because the
legacy shared conftest forces SQLite at import time; no SQLite fixture is used
as acceptance evidence.

The tests cover executable/hidden HTML removal before the security scanner,
visible prompt-injection quarantine, parser and streamed response size caps,
invalid and degraded PDF paths, redirect-loop limits, and same-source content
replay/new-version decisions.  A separate PostgreSQL-only probe uses the real
`kb_source_registry` and `kb_source_version` tables to verify the tenant/source
content-hash uniqueness boundary and rolls the transaction back.

## Verification

- `tests/knowledge_engine_v2/test_ing024_adversarial_inputs.py`: 7 passed.
- Existing parser/cleaner/scanner/idempotency regression: 44 passed without
  the SQLite-forcing parent conftest.
- CAT-004 pure outbound regression: 14 passed, 1 deselected (the deselected
  case is the legacy SQLite fixture test).
- `scripts/knowledge_engine_v2_ing024_pg_probe.py`: PostgreSQL PASS with
  duplicate rejection, cross-tenant allowance and rollback.
- `py_compile` and `git diff --check`: PASS.
