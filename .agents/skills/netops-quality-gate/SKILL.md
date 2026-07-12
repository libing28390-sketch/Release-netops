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
- Do not weaken assertions merely to make a failure pass.
- Distinguish failures caused by the current change from pre-existing failures and report both.
- Do not mutate production data or require external network access for routine verification.

## Delivery Evidence

Report exact commands, pass/fail counts, skipped checks, and remaining risk. Store a requested walkthrough under `docs/walkthrough/` per workspace rules.
