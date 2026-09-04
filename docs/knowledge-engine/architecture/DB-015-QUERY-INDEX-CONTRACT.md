# DB-015 Query Index Contract

## Contract summary

Exact, Alias, and Prefix resolution are bounded and tenant-aware. The V1
indexes include `ux_ai_document_document_id`, `ix_ai_document_vendor`, and
`ix_ai_document_status`; retrieval predicates also use `tenant_id`, `status`,
`product_series`, `product_model`, and `metadata_json`. `metadata_gin` covers
the structured extension path while typed equality remains the preferred
route.

## Performance and rollback

`EXPLAIN` plans and `varchar_pattern_ops` evidence are required for prefix
searches. DB-016 owns vector/FTS acceptance. The rollback path removes the
new index generation or returns to the V1 `rollback` plan without deleting
source rows.

## Final conclusion

The Exact/Alias/Prefix, tenant, status, vendor/product/version, EXPLAIN,
DB-016, V1, and rollback markers are present.

Final Conclusion: PASS
