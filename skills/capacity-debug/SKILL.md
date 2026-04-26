# Capacity Debug Skill

## Purpose
Troubleshoot `/api/capacity/*` errors quickly against real PostgreSQL schema.

## When to Use
- `500 Internal Server Error` in capacity endpoints
- SQL errors such as missing columns/tables
- data mismatch between UI and backend trend/forecast APIs

## Workflow
1. Read `backend/api/capacity.py`.
2. Compare SQL with actual PostgreSQL table definitions.
3. Query PostgreSQL (via MCP postgres) to verify runtime schema/data.
4. Patch minimal SQL/field mapping.
5. Verify with local function call or endpoint request.

## Guardrails
- Keep endpoint response shape unchanged.
- Prefer compatibility fixes over schema rewrites.
