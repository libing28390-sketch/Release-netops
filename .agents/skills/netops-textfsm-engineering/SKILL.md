---
name: netops-textfsm-engineering
description: Use when creating or debugging TextFSM templates, CLI parsers, or their catalog and sandbox.
---

# NetOps TextFSM Engineering

## Workflow

1. Identify the exact vendor, platform, software family, and raw output shape.
2. Keep raw collection separate from parsing and downstream normalization.
3. Use [template conventions](references/template-conventions.md) when creating or changing template fields, names, or state rules.
4. Validate representative, sanitized CLI samples through the existing TextFSM sandbox and affected consumers.

## Boundaries

- Templates belong in `backend/data/textfsm_templates/`.
- Sandbox, validation, and template-building logic belongs in `backend/services/textfsm_*.py`.
- Template APIs belong in `backend/api/textfsm_templates.py`; catalog UI belongs in the existing TextFSM pages.

## Safety and verification

- H3C TextFSM uses the `h3c_comware` parser family, with versioned variants when applicable. Keep Netmiko's `hp_comware` type at the transport boundary; see the template conventions reference.
- Keep device output sanitized and test with fixtures rather than live-device access.
- Run focused TextFSM tests and validate at least two representative output samples for changed templates.
