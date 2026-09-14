---
name: netops-pam-automation
description: Use when changing PAM sessions, command auditing, credential rotation, change orders, or privileged playbooks.
---

# NetOps PAM, Bastion Web Terminal & Change Automation

## Workflow

1. Trace privileged operations end-to-end: User auth & RBAC/ABAC check -> Access Scope verification -> Credential decryption (`vault_service.py`) -> SSH session proxy / Web terminal WebSocket (`pam_web.py`) -> Real-time command filter -> Tamper-proof audit logging (`pam_audit_service.py`).
2. Manage the strict Change Order state machine: `Draft -> Submitted -> Approved -> Executing -> Verified -> Completed / Rolled Back`.
3. Ensure automated password rotation pipelines verify connectivity with the new credential BEFORE committing changes to PostgreSQL, preserving atomic rollback capability.
4. Block dangerous and destructive commands in real-time unless tied to an approved Change Order execution context.
5. Record interactive terminal sessions in structured, replayable formats (e.g., timing logs + raw text) with cryptographic integrity hashes.

## Mandatory PAM & Security Conventions

- **Credential Vault & Crypto Security**:
  - All stored device passwords, enable secrets, and private keys must be encrypted using AES-256-GCM (`CREDENTIAL_ENCRYPTION_KEY`). Never store or log plaintext credentials.
  - Decrypted credentials must remain ephemeral in memory and never be serialized into API responses, error logs, or long-lived caches.
  - Password rotation jobs (`password_rotation_service.py`) must follow a two-phase commit: (1) apply new password to device, (2) verify login with new password, (3) persist encrypted record in DB. If step 2 fails, attempt immediate rollback to the previous credential.
- **Dangerous Command Interception & Guardrails**:
  - Intercept dangerous CLI patterns (e.g., `format`, `erase flash`, `reload`, `reboot`, `rm -rf`, `factory-reset`, `delete /unreserved`) in interactive terminal streams.
  - High-risk operations require explicit two-person approval (maker-checker rule) or an active Change Order reference.
- **Session Audit & Compliance**:
  - Terminal audit records must capture exact keystrokes, executed commands, matched alert rules, timestamps, client IP, and operator ID.
  - Audit log entries are append-only. Never provide delete or in-place update endpoints for PAM audit tables.

## Boundaries

- WebSocket terminal tunneling and SSH protocol adaptation belong in `backend/api/pam_web.py` and `backend/drivers/`.
- Audit storage, replay playback, and command pattern matching belong in `backend/services/pam_audit_service.py`.
- Credential encryption and rotation logic belong in `backend/services/vault_service.py` and `password_rotation_service.py`.
- Change order workflows and playbook runners belong in `backend/services/change_order_service.py` and `backend/api/change_orders/`.
- Frontend bastion terminals and audit logs belong in `src/pages/AccessCenterTab/` and `src/pages/PAMAuditTab.tsx`.

## Safety and Verification

- Run PAM & Change Order tests: `pytest backend/tests/ -k "pam or credential or change_order or playbook"`.
- Test dangerous command interception using simulated terminal inputs.
- Verify credential rotation failure paths and ensure failed rotations leave the database in a consistent, non-corrupted state.
