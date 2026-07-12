---
name: netops-backend
description: Implement and review Nexora NetOps FastAPI endpoints, service-layer business logic, authentication, scheduling, reporting, and backend integrations. Use for changes under backend/api, backend/services, backend/core, backend/engine, backend/repository, or backend/schemas.
---

# NetOps Backend

## Workflow

1. Trace the request from the router in `backend/api/` through services and database helpers before editing.
2. Keep routers focused on HTTP validation, authorization, status codes, and response contracts.
3. Put reusable business rules in `backend/services/`; put connection execution in `backend/drivers/` or `backend/engine/`.
4. Reuse `backend/core/rbac.py`, audit helpers, crypto helpers, and existing exception shapes.
5. Preserve PostgreSQL compatibility. Do not introduce SQLite-only SQL.
6. Add or update focused tests under `backend/tests/` for success, authorization, invalid input, and failure paths.

## Conventions

- Register new routers in `backend/main.py` under `/api`.
- Use Pydantic request models instead of untyped request dictionaries when the contract is stable.
- Never expose credentials, tokens, SNMP communities, or raw secrets in logs or responses.
- Avoid blocking network or filesystem calls inside async endpoints; use existing async drivers or offload deliberately.
- Preserve the API response shapes consumed by `src/hooks`, stores, and pages.

## Verification

Run the narrowest relevant pytest file first, then expand to `pytest backend/tests`. For contract changes, run `npm run lint` as well.
