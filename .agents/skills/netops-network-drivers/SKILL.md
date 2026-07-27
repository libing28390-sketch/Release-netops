---
name: netops-network-drivers
description: Add, troubleshoot, and review multi-vendor network integrations for SSH, CLI execution, SNMP telemetry, TextFSM parsing, topology discovery, diagnostics, and IP location. Use for device compatibility or changes in backend/drivers, backend/engine, and network-facing services.
---

# NetOps Network Drivers

## Workflow

1. Identify vendor, platform, software family, transport, command, expected output, and failure mode.
2. Read the current `vendor` and `platform` from both `physical_assets` and the linked `devices` row before diagnosing SSH or CLI failures. Treat a user-initiated vendor switch as valid current test state.
3. Trace form/import input, backend normalization, asset-device synchronization, command-catalog selection, and driver selection as one end-to-end mapping before changing vendor behavior.
4. Normalize vendor differences at the driver, parser, normalizer, or shared platform-mapping boundary instead of scattering conditions through APIs.
5. Preserve connection timeouts, legacy SSH fallback, credential redaction, and structured error codes.
6. Prefer captured fixture output and mock drivers for tests; use a live device only for an authorized read-only verification and never require it for CI.

## Mandatory Vendor-Platform-Command Gate

`vendor`, `platform`, Netmiko `device_type`, and the command catalog are one contract. A change is incomplete unless all four agree.

| Vendor | Stored/canonical platform | Netmiko family | Query command family |
| --- | --- | --- | --- |
| Cisco | `cisco_ios` or explicit Cisco family | `cisco_ios` | `show ...` |
| Huawei | `huawei_vrp` / `huawei_vrpv8` | `huawei` | `display ...` |
| H3C | `hp_comware`, normalized to `h3c_comware` for catalogs | `hp_comware` | `display ...` |
| Juniper | `juniper_junos` | `juniper_junos` | Junos `show ...` |
| Arista | `arista_eos` | `arista_eos` | EOS `show ...` |
| Ruijie | `ruijie_rgos` | `ruijie_os` | RGOS catalog |

- Never infer vendor from model alone; model names such as `S6800` are ambiguous across vendors.
- When the user changes vendor, replace an incompatible stale platform and clear or revalidate vendor-specific model data.
- Apply the same validation to UI forms, Excel imports, API create/update, copied assets, and linked-device synchronization.
- For a recognized vendor, never silently fall back to Cisco commands when platform is missing or incompatible. Repair the mapping or return an explicit validation error.
- Automation quick queries and backend operational catalogs must derive commands from the same normalized platform contract.
- H3C TextFSM/NTC parsing is a separate canonical boundary: always use `hp_comware` for parser platform arguments and custom filenames (`hp_comware_<command>.textfsm`). Keep `h3c_comware`/`h3c_comware9` only for device identity, Netmiko/driver selection, and command catalogs; normalize those values to `hp_comware` before Playbook parsing, inspections, operational collectors, topology/LLDP parsing, and normalizers. Existing `h3c_comware_*` files are legacy fallbacks only; do not create new ones.
- Interface identity must use the shared canonicalizer in `backend/core/interface_utils.py`; never compare vendor display names literally. At minimum, treat H3C `XGE/FGE/HGE`, Huawei `10GE/40GE/100GE`, Cisco `Te/Fo/Hu` and long forms such as `Ten-GigabitEthernet`, `FortyGigE`, and `HundredGigE` as equivalent 10G/40G/100G families. Preserve the raw name for display and member details, but use the canonical key for LLDP matching, aggregation membership, interface upserts, and topology deduplication.
- Manual topology discovery refreshes the read-only interface summary, aggregation inventory, and LLDP neighbors in one topology run; it is not the full CMDB interface/IP status job. The aggregation command is authoritative for LAG membership; a successful device snapshot detaches members missing from the latest result and marks missing neighbor observations stale immediately. Full interface/IP status collection remains a separate job and must use PostgreSQL-compatible boolean values.
- SNMPv2c credentials are Community-based, not SSH-account-based: require `snmp_community`, keep `snmp_server` optional, and use the device management IP when `snmp_server` is blank. Resolve SNMP through `resolve_collector_credentials` so diagnostics, tests, background collection, playbooks, and interface collection share the same target/community/port contract.
- Before delivery, test at least Cisco, Huawei, and H3C mappings, including a vendor-switch regression proving the old platform does not remain.

## Boundaries

- Generic transport behavior belongs in `backend/drivers/` or `backend/engine/drivers/`.
- Domain collection belongs in services such as topology, diagnostics, telemetry, inspection, and IP locator.
- Vendor normalization belongs in `backend/services/normalizers/` or TextFSM templates.
- UI-visible failures must retain stable codes used by `src/utils/connectionHelpers.ts`.

## Safety and Verification

- Treat show/query commands as read-only; require explicit user authorization for configuration changes.
- Never log passwords, private keys, enable secrets, or SNMP communities.
- Test authentication failure, timeout, unreachable host, unsupported command, malformed output, and fallback behavior.
- For command-dispatch incidents, report the observed database vendor/platform, normalized catalog key, Netmiko device type, and exact read-only command selected; do not label the issue an SSH algorithm failure until this chain is verified.
