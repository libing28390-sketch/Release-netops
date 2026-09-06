# CAT-006 Cisco Catalyst / C9300 Product Hierarchy

## Decision

CAT-006 establishes the first reviewed product hierarchy sample for Cisco Catalyst 9300. The explicit hierarchy is:

```text
cisco
  └── catalyst_9300
        └── c9300
              ├── C9300-24T
              ├── C9300-48P
              └── C9300-48U
```

The sample is a catalog input artifact, not a production migration. Model rows remain `draft` until an exact versioned Cisco source is captured and CAT-009/CAT-011 conflict review is complete.

## Identity boundaries

- Cisco, Catalyst 9300, C9300 and an exact SKU are separate identity levels.
- IOS-XE `17.9.x` and `17.18.x` are applicability/version facts, not product parents.
- `cisco_ios` is an advisory retrieval/parser hint; it cannot authorize a device, credential, driver execution or write command.
- `C9300`, `Catalyst93` and `Catalyst 9300` resolve only to a series candidate. A partial SKU returns candidates and asks for clarification; unknown values return UNKNOWN.

## Provenance

All source references are inside the frozen CAT-001 Cisco exact host/path boundary. The product page and 17.9/17.18 command references are typed under CAT-002. No live collection or production DDL is part of CAT-006.

## Acceptance and rollback

Deterministic tests cover model uniqueness, Cisco allowlist matching, ambiguity, software/driver orthogonality and no-production-DDL rollback. Disable CAT-006 reads to return to the V1 advisory resolver while preserving V1 metadata.

Final Conclusion: PASS
