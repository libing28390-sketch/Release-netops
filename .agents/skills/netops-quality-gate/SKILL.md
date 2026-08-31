---
name: netops-quality-gate
description: Validate Nexora NetOps changes with risk-based tests, TypeScript checks, production builds, API contract review, regression analysis, and security checks. Use before delivery, after cross-layer changes, or when diagnosing test and build failures.
---

# NetOps Quality Gate

## Risk-Based Gate

1. Inspect the diff and map each changed behavior to existing or new tests.
2. Run focused tests first for fast feedback.
3. Run `pytest backend/tests` for backend, database, workflow, or network-service changes.
4. Run `npm run lint` for frontend or API contract changes.
5. Run `npm run build` for frontend, routing, packaging, or release changes.
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

Before delivery, run the repository PostgreSQL-only policy scanner. Any active SQLite code or test is a blocking quality-gate failure; do not allowlist new violations.
