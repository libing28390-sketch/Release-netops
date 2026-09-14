---
name: netops-quality-gate
description: Use when selecting or running focused tests, builds, contract checks, or security validation for a change.
---

# NetOps Quality Gate

## Risk-Based Gate

1. Inspect the diff and map each changed behavior to existing or new tests.
2. Run focused tests first. For local backend, database, or network changes, select affected modules and contract tests; expand when failures or shared dependencies justify it.
3. Run `pytest backend/tests` for formal release candidates, explicit full-regression requests, or changes to shared authentication, database/test infrastructure, or broad cross-module behavior. A workflow-only change does not by itself require the full backend suite.
4. Run `npm run lint` for frontend or API contract changes. Run `npm run build` when frontend output, routing, bundling, or deployment asset behavior is affected; use an isolated output directory if existing build artifacts must be preserved.
5. For release filtering and CI wiring, check configuration syntax, affected platform paths, relevant release contracts, and the changed artifact behavior. For agent/skill instructions, validate format, discovery and relevant behavior instead of unrelated application tests.
6. Check secrets, authorization, audit logging, concurrency, error handling, and backward compatibility.

## Test Expectations

- Cover success, invalid input, permission denial, empty data, and dependency failure.
- Use mocks or fixtures for devices and external systems.
- PostgreSQL is the only supported persistence backend for runtime and tests. Every test that touches persistence, schema, migrations, constraints, transactions, indexes, or repositories must use the shared isolated PostgreSQL fixtures.
- Never add `sqlite3`, `:memory:`, SQLite database files, `sqlite_master`, `PRAGMA`, SQLite URLs, SQLite-only SQL, or a fixture that clears `DATABASE_URL`/sets `_USE_PG=False`.
- Validate schema and migration behavior with PostgreSQL catalogs and real PostgreSQL transactions. Do not use SQLite behavior as evidence for PostgreSQL compatibility.
- Temporary PostgreSQL databases must use an unmistakable test-only name, reject production targets, close pools and connections, and be force-dropped even after setup or assertion failures.
- Do not weaken assertions merely to make a failure pass.
- Distinguish failures caused by the current change from pre-existing failures and report both.
- Do not mutate production data or require external network access for routine verification.

## Delivery Evidence

Report exact commands, pass/fail counts, skipped checks, and remaining risk. Store a requested walkthrough under `docs/walkthrough/` per workspace rules.

Run the repository PostgreSQL-only policy scanner for backend, database or persistence-related changes and formal release candidates. Any active SQLite code or test remains a release blocker; do not allowlist new violations. Pure agent/skill instruction edits do not require this scanner.

The coordinator owns the combined verification plan. Workers run their assigned checks; run shared checks once after integration and reuse evidence while the relevant code remains unchanged. Report existing failures accurately without repairing unrelated code or claiming overall release readiness.
