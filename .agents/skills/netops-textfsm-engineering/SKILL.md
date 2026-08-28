---
name: netops-textfsm-engineering
description: Author, test, and maintain TextFSM parsing templates for multi-vendor network CLI outputs (Cisco, Huawei, H3C, etc.), build template sandboxes, and ensure structured parsing consistency. Use for changes under backend/data/textfsm_templates/, backend/services/textfsm*, backend/api/textfsm_templates.py, or frontend TextFSM management pages.
---

# NetOps TextFSM Template Engineering & Parsing Sandbox

## Workflow

1. Obtain and scrub raw CLI command output from sample network devices across target vendors (Cisco IOS, Huawei VRP, H3C Comware).
2. Author or modify `.textfsm` templates with explicit `Value` definitions and clean state transition rules.
3. Test templates against multiple realistic CLI output variations using `textfsm_sandbox_service.py` before committing to the repository.
4. Adhere strictly to canonical platform naming rules (e.g., always use `hp_comware` for H3C templates).
5. Ensure normalized field names match downstream consumer contracts (Topology, IP Locator, Inspection, Asset inventory).

## Mandatory Template Conventions & Platform Rules

- **Canonical File Naming & Platform Keys**:
  - Cisco IOS templates: `cisco_ios_<command>.textfsm` (e.g., `cisco_ios_show_ip_interface_brief.textfsm`).
  - Huawei VRP templates: `huawei_vrp_<command>.textfsm` (e.g., `huawei_vrp_display_ip_interface_brief.textfsm`).
  - H3C Comware templates: **ALWAYS** use `hp_comware_<command>.textfsm` (e.g., `hp_comware_display_ip_interface_brief.textfsm`).
  - *Strict Rule*: Do NOT create new `h3c_comware_*` template files. Normalize all H3C platform variations (`h3c_comware`, `h3c_comware9`) to `hp_comware` before invoking the TextFSM parser.
- **TextFSM State Machine Best Practices**:
  - Use `Filldown` for global or header-level attributes that apply across multiple row records.
  - Use `Required` on primary keys (such as `INTERFACE` or `NEIGHBOR_IP`) to prevent incomplete or empty row emission.
  - Avoid overly greedy regex matches (`.*`); prefer precise character classes (e.g., `\S+`, `[0-9]+(?:\.[0-9]+){3}`, `[0-9a-fA-F:.-]+`).
  - Explicitly handle line-wrapped CLI outputs and varying whitespace padding across firmware versions.
- **Unified Field Schema across Vendors**:
  - Ensure standard fields share consistent naming across vendor templates for identical concepts:
    - Interface brief: `INTERFACE`, `IP_ADDRESS`, `STATUS`, `PROTOCOL`, `DESCRIPTION`
    - LLDP neighbors: `LOCAL_INTERFACE`, `NEIGHBOR_NAME`, `NEIGHBOR_INTERFACE`, `CHASSIS_ID`, `MANAGEMENT_IP`
    - MAC table: `VLAN`, `MAC_ADDRESS`, `TYPE`, `PORT`
    - ARP table: `IP_ADDRESS`, `MAC_ADDRESS`, `INTERFACE`, `VLAN`

## Boundaries

- Raw template definitions reside in `backend/data/textfsm_templates/`.
- Template validation, sandbox execution, and dynamic template building belong in `backend/services/textfsm_*.py`.
- Template management APIs belong in `backend/api/textfsm_templates.py`.
- Frontend template catalog, interactive sandbox, and test benches belong in `src/pages/TextFSMTemplatesTab.tsx` and `src/pages/textfsmPlatformCatalog.ts`.

## Safety and Verification

- Run TextFSM unit and catalog tests: `pytest backend/tests/ -k "textfsm" && npm test -- --run src/pages/TextFSMTemplatesTab.test.tsx`.
- Validate every new or edited template against at least two distinct raw output samples (including edge cases with missing columns or multi-line banners).
- Verify that parser output is valid JSON and contains zero missing required keys.
