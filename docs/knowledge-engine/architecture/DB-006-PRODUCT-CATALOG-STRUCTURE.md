# DB-006 Product Catalog Structure

## Contract summary

The reviewed hierarchy is Vendor → Family → Series → Model → Alias. The
canonical entities are `kb_product_family`, `kb_product_series`,
`kb_product_model`, and `kb_product_alias`; `device_types` and legacy
`ai_document` rows remain compatibility projections, not replacements for
the hierarchy. `ProductResolver.SERIES_ALIASES` is a bounded compatibility
adapter.

## Security and rollback

Every row carries tenant scope and review status. An alias may return a
candidate list but cannot authorize a driver or a write. Rollback disables the
new catalog read projection and retains the V1 metadata and reviewed seed.

## Final conclusion

The DB-006 hierarchy, tenant boundary, V1 compatibility, and 回滚 contract
are documented.

Final Conclusion: PASS
