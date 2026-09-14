---
name: netops-network-drivers
description: Use when changing device connections, CLI drivers, vendor-platform mapping, or vendor-specific command execution.
---

# NetOps Network Drivers

## Workflow

1. Identify the affected vendor, platform, software family, transport, command, and failure.
2. Trace asset/device values through normalization, driver selection, and command dispatch before changing behavior.
3. Keep vendor differences at driver, parser, normalizer, or shared mapping boundaries.
4. Use fixtures and mock drivers for routine tests; preserve timeouts, SSH fallbacks, credential redaction, and structured errors.
5. Read [the vendor-platform contract](references/vendor-platform-contract.md) when changing device mapping, interface identity, or command selection.

## Boundaries

- Generic transport belongs in `backend/drivers/` or `backend/engine/drivers/`.
- Protocol parsing and normalization belong in their existing parser and normalizer layers.
- Telemetry, topology, diagnostics, and IP location workflows use their domain skills for task-specific rules.

## Safety and verification

- Treat query commands as read-only. Configuration changes require explicit user authorization, audit, and a recovery path.
- Never log passwords, private keys, enable secrets, or SNMP communities.
- Use live devices only for explicitly authorized read-only verification; tests must not depend on them.
- For dispatch failures, verify observed vendor/platform, normalized catalog key, driver type, and selected command before attributing the cause to SSH.
