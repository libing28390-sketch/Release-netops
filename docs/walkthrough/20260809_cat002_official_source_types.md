# CAT-002 Official Source Types Walkthrough

CAT-002 freezes five explicit source types: official URL, product page,
configuration guide, command reference, and release note/version explanation.
Each type has required provenance, version scope, parser boundaries, and
fail-closed behavior.

Verification: CAT-002 focused tests 5 passed; CAT-001/2 plus DB-006/8
compatibility set 23 passed; YAML parse, compileall, diff check and secret scan
passed with 0 matches. No database, API, frontend, device, or remote source was
mutated.
