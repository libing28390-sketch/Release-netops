# PAM Implementation Plan (MVP -> Production)

## Scope
- Build least-privilege terminal access for managed assets.
- Support `normal` (read-only) and `admin` (privileged) access levels.
- Add approval gate for privileged access.

## Current Baseline (already in code)
- Asset UI supports dual-account fields.
- `devices` has `enable_password`, `priv_username`, `credential_source`, `vault_path`.
- New backend endpoint: `POST /api/pam/access-request` (MVP).
- New tables:
  - `pam_access_requests`
  - `pam_session_tokens`

## Phase 1 (MVP completed in this iteration)
1. Asset credential model alignment:
   - `physical_assets` now includes:
     - `admin_username`, `admin_password`, `enable_password`
     - `auth_model`, `credential_source`, `vault_path`
     - `requires_strict_audit`
2. UI entry:
   - Asset list action includes “Connect Terminal”.
   - Modal supports selecting `User Access` vs `Admin Access`.
3. Access request API:
   - `normal` -> immediate `approved`
   - `admin` -> `pending` (approval required)

## Phase 2 (next)
1. Approval workflow:
   - Add reviewer APIs:
     - `GET /api/pam/access-requests`
     - `POST /api/pam/access-requests/{id}/approve`
     - `POST /api/pam/access-requests/{id}/reject`
2. Session token policy:
   - single-use tokens
   - token TTL <= 5 minutes
   - bind token to `asset_id`, `user`, `access_level`
3. Frontend:
   - show pending queue + status polling
   - add 2FA step for approved admin request

## Phase 3 (production hardening)
1. Vault-first privileged secrets:
   - privileged password should not be persisted as long-lived local plaintext.
2. Gateway access:
   - web terminal through backend proxy
   - external client through ephemeral local proxy port
3. Audit:
   - command stream recording
   - immutable access timeline: request/approve/connect/disconnect

## DB Migration Notes
- Migration is implemented via `ensure_column` and `CREATE TABLE IF NOT EXISTS`.
- Existing deployments can roll forward without manual SQL.

## Acceptance Criteria
1. User can request terminal access from Asset page.
2. `normal` access request is granted and token issued.
3. `admin` access request enters pending status.
4. Asset dual-account data is persisted and retrievable.
5. No regression for existing asset CRUD and linked device sync.

## Risks
- Mixed legacy credential fields may cause operator confusion.
- If `admin_password` is local-only for too long, security posture is weaker than Vault/JIT.

## Recommendation
- Treat current MVP as control-plane foundation.
- Prioritize Phase 2 approval + token consumption and Phase 3 vault-first rollout.
