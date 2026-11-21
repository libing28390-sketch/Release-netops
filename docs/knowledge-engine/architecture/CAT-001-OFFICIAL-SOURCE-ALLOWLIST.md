# CAT-001 Official Source Allowlist

## Contract summary

This V1 report records the allowlist boundary for official knowledge sources.
Huawei and Cisco sources are accepted only through HTTPS vendor-owned hosts.
The default-deny rule applies before redirect validation, and an exact
allowlisted path is required after a redirect is followed. `DB-008` owns the
source registry projection; `CAT-003` and `CAT-004` provide the additive
validation and secure outbound boundaries.

## Security and rollback

`official_url` is provenance, not device-write authority. Unsupported hosts,
schemes, redirects, and out-of-scope paths remain rejected. A rollback keeps
the V1 source records and disables the additive catalog reads; it does not
delete historical source evidence.

## Final conclusion

The CAT-001 allowlist, HTTPS, default-deny, exact-match, redirect, DB-008,
CAT-003, and CAT-004 boundaries are present and reviewable.

Final Conclusion: PASS
