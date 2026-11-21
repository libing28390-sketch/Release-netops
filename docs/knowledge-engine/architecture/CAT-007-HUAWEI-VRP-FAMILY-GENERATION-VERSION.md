# CAT-007 Huawei VRP Family / Generation / Version

## Decision

CAT-007 separates Huawei software identity from product and execution identity:

```text
huawei
└── os_family: vrp
    ├── generation: vrp5
    │   └── release_train: V200
    │       └── V200R001C00 (draft)
    └── generation: vrp8
        └── release_train: V300
            ├── V300R024C10SPC500 (draft, primary)
            └── V300R023C00SPC500 (draft, compatibility)
```

The artifact is a reviewed seed, not a production migration. Original version strings remain immutable facts; normalized versions and sort keys are derived for exact lookup and vendor-scheme ordering.

## Resolution and UNKNOWN rules

- `VRP` without a generation returns VRP5/VRP8 candidates and requires clarification.
- `V200` or `V300` alone identifies a release-train candidate, not an exact version or driver.
- `V600` and other values outside this first batch are preserved as V1 values and return UNKNOWN/review, never silently mapped.
- Malformed or wrong-scheme strings are rejected or held pending review.
- Only an explicit reviewed generation-to-platform mapping may expose `huawei_vrp`/`huawei_vrpv8`; software text never selects a connection driver.

## Provenance and rollback

Source references reuse CAT-001 Huawei exact HTTPS paths and CAT-002 typed sources. CAT-007 adds no production DDL. Disable the V2 OS/software resolver to restore V1 metadata filters; retain original strings and seed artifacts.

Final Conclusion: PASS
