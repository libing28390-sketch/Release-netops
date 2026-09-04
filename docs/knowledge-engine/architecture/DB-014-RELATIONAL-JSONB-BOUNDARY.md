# DB-014 Relational and JSONB Boundary

## Contract summary

High-frequency relation fields (关系字段) remain typed columns while bounded extension
metadata stays in `metadata_json`, JSONB, `acl_json`, `scope_json`, and
`error_json`. The boundary is indexed with `metadata_gin`,
`ix_ai_document_vendor`, and `ix_ai_document_status`; typed values are not
hidden in an unbounded JSON fallback.

## Query and rollback

Tenant and uniqueness constraints are relational authorization boundaries.
`EXPLAIN` evidence is required for high-volume paths. DB-015 and DB-016 own
the query/index and vector acceptance gates. A rollback drops only additive
indexes/projections and leaves V1 values intact.

## Final conclusion

The typed, JSONB, tenant, 唯一性, 权限, EXPLAIN, DB-015, DB-016, V1, and 回滚
decisions are documented.

Final Conclusion: PASS
