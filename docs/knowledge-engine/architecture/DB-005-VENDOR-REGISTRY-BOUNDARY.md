# DB-005 Vendor Registry Boundary

## Contract summary

The vendor boundary keeps `kb_vendor`/`kb_vendors`, `platform_profiles`, and
`kb_vendor_platform` as distinct concepts. `SYSTEM_PROFILES` is the runtime
platform projection and does not become a knowledge vendor identity. The
`ai_provider` registry is also independent: an AI provider cannot authorize a
network driver or change the vendor catalog.

## Security and rollback

All registry rows are tenant-scoped and PostgreSQL-backed. A failed or
partial catalog update rolls back its transaction and leaves V1 platform and
provider rows untouched. The rollback path disables the new projection while
retaining the reviewed source and audit evidence.

## Final conclusion

The DB-005 decision boundary, `kb_vendor`, `kb_vendors`, `platform_profiles`,
`kb_vendor_platform`, `SYSTEM_PROFILES`, `ai_provider`, PostgreSQL, and 回滚
markers are present.

Final Conclusion: PASS
