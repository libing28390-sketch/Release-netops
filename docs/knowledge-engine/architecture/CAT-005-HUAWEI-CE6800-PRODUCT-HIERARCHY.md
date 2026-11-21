# CAT-005 Huawei CloudEngine / CE6800 Product Hierarchy

## Decision

CAT-005 establishes the first reviewed product hierarchy sample for Huawei CloudEngine 6800. The hierarchy is explicit and additive:

```text
huawei
  └── cloudengine_6800
        └── ce6800
              ├── CE6860-SAN
              ├── CE6885-48YS8CQ
              └── CE6881-48S6CQ
```

The sample is a catalog input artifact, not a production migration. Model rows remain `draft` until an exact versioned official source has been captured and CAT-009/CAT-011 conflict review is complete.

## Identity boundaries

- `vendor_id`, family code, series code and exact model code are separate identity fields.
- `V300R024C10SPC500` and `V300R023C00SPC500` are applicability/version facts, not product parents.
- `huawei_vrp`/`huawei_vrpv8` is an advisory parser and driver compatibility hint; it grants no device, credential or write authority.
- `CE68`, `CE6800`, `CE68XX` and `CloudEngine 6800` are series candidates. A partial model prefix returns candidates and asks for clarification; it never selects the first model.

## Provenance

All source references are inside the frozen CAT-001 Huawei host/path boundary and use CAT-002 source types. The product-page sample is the Huawei Enterprise Support CE6860 SAN path; configuration and command references are the reviewed VXLAN and MD-CLI paths. No live collection or production DDL is part of CAT-005.

## Acceptance and rollback

The artifact passes deterministic uniqueness, path allowlist, version orthogonality, ambiguity and no-driver-authority tests. Rollback disables CAT-005 reads and returns resolution to the V1 advisory adapter; V1 metadata and device types are retained unchanged.

Final Conclusion: PASS
