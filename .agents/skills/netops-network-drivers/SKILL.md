---
name: netops-network-drivers
description: Add, troubleshoot, and review multi-vendor network integrations for SSH, CLI execution, SNMP telemetry, TextFSM parsing, topology discovery, diagnostics, and IP location. Use for device compatibility or changes in backend/drivers, backend/engine, and network-facing services.
---

# NetOps Network Drivers

## Workflow

1. Identify vendor, platform, software family, transport, command, expected output, and failure mode.
2. Trace driver selection through the factories before changing vendor behavior.
3. Normalize vendor differences at the driver, parser, or normalizer boundary instead of scattering conditions through APIs.
4. Preserve connection timeouts, legacy SSH fallback, credential redaction, and structured error codes.
5. Prefer captured fixture output and mock drivers for tests; never require live production devices for CI.

## Boundaries

- Generic transport behavior belongs in `backend/drivers/` or `backend/engine/drivers/`.
- Domain collection belongs in services such as topology, diagnostics, telemetry, inspection, and IP locator.
- Vendor normalization belongs in `backend/services/normalizers/` or TextFSM templates.
- UI-visible failures must retain stable codes used by `src/utils/connectionHelpers.ts`.

## Safety and Verification

- Treat show/query commands as read-only; require explicit user authorization for configuration changes.
- Never log passwords, private keys, enable secrets, or SNMP communities.
- Test authentication failure, timeout, unreachable host, unsupported command, malformed output, and fallback behavior.
